"""Real MCP stdio -> installed native API -> original loopback HTTP."""

import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import anyio
import pytest
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests_native.wire import Wire

REPOSITORY = Path(__file__).resolve().parents[1]


def server_process(
    origin,
    accounts,
    *,
    budget_requests=None,
    features=None,
    state_dir=None,
    download_dir=None,
    setup_script="",
):
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith("LIBRUS_"):
            del environment[name]
    environment.update(
        {
            "LIBRUS_ACCOUNTS": json.dumps(
                [
                    {
                        "alias": alias,
                        "username": login,
                        "password": "not-a-real-password",  # pragma: allowlist secret - loopback only
                        **({"messaging_backend": account[2]} if len(account) == 3 else {}),
                    }
                    for account in accounts
                    for alias, login in [account[:2]]
                ]
            ),
            "LIBRUS_CONTEXT_KEY": bytes(range(32)).hex(),
            "NATIVE_TEST_ORIGIN": origin,
        }
    )
    if budget_requests is not None:
        environment["NATIVE_TEST_BUDGET_REQUESTS"] = str(budget_requests)
    if features is not None:
        environment["LIBRUS_FEATURES"] = json.dumps(features)
    if state_dir is not None:
        environment["LIBRUS_STATE_DIR"] = str(state_dir)
    if download_dir is not None:
        environment["LIBRUS_DOWNLOAD_DIR"] = str(download_dir)
    script = (
        setup_script
        + "\n"
        + """import os
from librus_python_api import ConnectionSettings, RequestBudget
from librus_mcp.config import load_config
from librus_mcp.server import create_server
origin = os.environ["NATIVE_TEST_ORIGIN"]
budget = None if "NATIVE_TEST_BUDGET_REQUESTS" not in os.environ else RequestBudget(
    max_requests=int(os.environ["NATIVE_TEST_BUDGET_REQUESTS"]))
create_server(load_config(), connection=ConnectionSettings(
    synergia_origin=origin, api_origin=origin, download_origin=origin,
    messages_origin=origin), budget=budget).run(transport="stdio")
"""
    )
    return StdioServerParameters(
        command=sys.executable, args=["-c", script], cwd=REPOSITORY, env=environment
    )


@pytest.mark.asyncio
async def test_four_logins_share_traffic_but_not_sessions_and_catalog_does_not_login():
    assert importlib.util.find_spec("librus_apix") is None
    accounts = [(f"account-{number}", f"login-{number}") for number in range(4)]
    async with Wire().serve() as wire:
        with anyio.fail_after(30):
            async with stdio_client(server_process(wire.origin, accounts)) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    catalog = listed.tools
                    assert {tool.name for tool in catalog} == {
                        "list_accounts",
                        "get_student_information",
                        "get_final_grades",
                        "get_grades",
                        "get_attendance",
                        "get_grades_window",
                        "get_attendance_window",
                        "get_attendance_detail",
                        "get_attendance_frequency",
                        "get_subject_frequency",
                        "get_timetable",
                        "get_announcements",
                        "get_agenda",
                        "get_agenda_detail",
                        "get_homework",
                        "get_homework_detail",
                        "get_completed_lessons",
                        "get_messages",
                        "get_message_content",
                        "get_recipient_types",
                        "get_recipient_choices",
                        "get_recipients",
                    }
                    assert all(tool.output_schema for tool in catalog)
                    assert (
                        len(listed.model_dump_json(by_alias=True, exclude_unset=True).encode())
                        < 96 * 1024
                    )
                    result = await session.call_tool("list_accounts", {})
                    assert result.structured_content == {
                        "items": [{"account_alias": alias} for alias, _ in accounts]
                    }
                    assert wire.calls == []
                    workload_started = time.monotonic()
                    results = await asyncio.gather(
                        *[
                            session.call_tool("get_student_information", {"account_alias": alias})
                            for alias, _ in accounts
                        ]
                    )
                    for result, (alias, login) in zip(results, accounts, strict=True):
                        assert not result.is_error, result
                        data = result.structured_content
                        assert data["data"]["school"] == login
                        assert data["data"]["identity"]["owner"]["id"] == login
                        assert data["data"]["identity"]["student"]["id"] == "shared-pupil"
                        assert data["observation"]["account"] == alias
                    assert wire.logins == {login: 1 for _, login in accounts}
                    assert 1 <= wire.peak <= 2
                    calls = len(wire.calls)
                    cached = await session.call_tool(
                        "get_student_information", {"account_alias": accounts[0][0]}
                    )
                    assert not cached.is_error
                    assert wire.logins == {login: 1 for _, login in accounts}
                    assert wire.calls[calls:] == [("GET", "/informacja", accounts[0][1])]
                    calls = len(wire.calls)
                    bad = await session.call_tool(
                        "get_student_information", {"account_alias": "unknown"}
                    )
                    assert bad.is_error and bad.structured_content == {
                        "error": {"code": "INVALID_INPUT"}
                    }
                    assert len(wire.calls) == calls
                    # One shared default token budget, not a burst per alias.
                    # Include connection establishment in the client workload
                    # clock. Arrival timestamps can be compressed by DNS/TCP
                    # delays and are not exact scheduler dispatch timestamps.
                    for index, dispatched_at in enumerate(wire.dispatch_times, start=1):
                        assert index <= 11 + 5 * (dispatched_at - workload_started)


@pytest.mark.asyncio
async def test_native_grade_attendance_contracts_and_effect_annotations():
    async with Wire().serve() as wire:
        with anyio.fail_after(20):
            async with stdio_client(server_process(wire.origin, [("account", "login")])) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                    for name in ("get_grades", "get_attendance"):
                        assert tools[name].annotations.read_only_hint is False
                        properties = tools[name].input_schema["properties"]
                        assert "account_alias" in properties and "scope" in properties
                        assert "student_alias" not in properties and "sort_by" not in properties
                    grades = await session.call_tool(
                        "get_grades", {"account_alias": "account", "scope": "week"}
                    )
                    assert not grades.is_error, grades
                    assert grades.structured_content["items"][0]["raw"] == "4+"
                    assert grades.structured_content["items"][0]["counts_toward_average"] is None
                    assert "href" not in grades.structured_content["items"][0]
                    assert grades.structured_content["scope"] == "week"
                    assert grades.structured_content["pagination"]["consistency"] == "best_effort"
                    final = await session.call_tool(
                        "get_final_grades", {"account_alias": "account"}
                    )
                    assert not final.is_error, final
                    assert final.structured_content["items"][0]["annual"] == {
                        "availability": "available",
                        "raw": "5",
                    }
                    attendance = await session.call_tool(
                        "get_attendance", {"account_alias": "account"}
                    )
                    assert not attendance.is_error, attendance
                    assert attendance.structured_content["items"][0]["symbol"] == "nb"
                    before = len(wire.calls)
                    invalid = await session.call_tool(
                        "get_grades",
                        {"account_alias": "account", "scope": "private-sensitive-value"},
                    )
                    assert invalid.is_error
                    assert invalid.structured_content == {"error": {"code": "INVALID_INPUT"}}
                    assert "private-sensitive-value" not in invalid.model_dump_json()
                    assert len(wire.calls) == before


@pytest.mark.asyncio
async def test_rejected_account_and_parse_failure_are_classified_not_empty():
    async with Wire().serve() as wire:
        with anyio.fail_after(20):
            async with stdio_client(
                server_process(wire.origin, [("good", "login"), ("bad", "denied")])
            ) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    bad = await session.call_tool(
                        "get_student_information", {"account_alias": "bad"}
                    )
                    assert bad.is_error and bad.structured_content == {
                        "error": {"code": "CREDENTIALS_REJECTED"}
                    }
                    assert wire.logins["denied"] == 1
                    bad_again = await session.call_tool(
                        "get_student_information", {"account_alias": "bad"}
                    )
                    assert bad_again.is_error
                    assert wire.logins["denied"] == 1
                    wire.bad_profile = True
                    parsed = await session.call_tool(
                        "get_student_information", {"account_alias": "good"}
                    )
                    assert parsed.is_error and parsed.structured_content == {
                        "error": {"code": "PARSE"}
                    }
                    assert "unrecognized sensitive page" not in parsed.model_dump_json()


@pytest.mark.asyncio
async def test_full_mcp_result_size_limit_returns_explicit_error(monkeypatch):
    import librus_mcp.server as module
    from librus_mcp.config import AppConfig
    from librus_mcp.server import create_server

    config = AppConfig.model_validate(
        {
            "accounts": [
                {
                    "alias": "fixture",
                    "username": "login",
                    "password": "fixture-only",  # pragma: allowlist secret - fixture only
                }
            ],
            "context_key": bytes(range(32)).hex(),
        }
    )
    server = create_server(config)

    @server.tool()
    async def fixture_large_output() -> dict[str, str]:
        return {"value": "\u017c" * 200}

    monkeypatch.setattr(module, "MAX_RESULT_BYTES", 400)
    result = await server.call_tool("fixture_large_output", {})
    assert result.is_error and result.structured_content == {"error": {"code": "LIMIT"}}
    assert "\u017c" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("records", [3, 100])
async def test_four_account_cold_and_warm_mixed_workload_remains_bounded_and_isolated(records):
    accounts = [(f"account-{number}", str(71 + number)) for number in range(4)]
    async with Wire().serve() as wire:
        wire.message_count = records
        with anyio.fail_after(60):
            async with (
                stdio_client(server_process(wire.origin, accounts)) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                for _ in range(2):
                    results = await asyncio.gather(
                        *[
                            session.call_tool(
                                name,
                                {"account_alias": alias}
                                | (
                                    {"limit": records, "max_pages": 2}
                                    if name == "get_messages"
                                    else {}
                                ),
                            )
                            for alias, _ in accounts
                            for name in ("get_grades", "get_attendance", "get_messages")
                        ]
                    )
                    for index, result in enumerate(results):
                        assert not result.is_error, result
                        alias, login = accounts[index // 3]
                        assert result.structured_content["observation"]["account"] == alias
                        assert result.structured_content["identity"]["owner"]["id"] == login
                        assert len(result.model_dump_json(by_alias=True).encode()) <= 512 * 1024
                        if index % 3 == 2:
                            items = result.structured_content["items"]
                            assert len(items) == records
                            assert all(item["reference"]["account"] == alias for item in items)
                            assert all(
                                item["summary"]["subject"].endswith("for " + login)
                                for item in items
                            )
                    assert wire.logins == {login: 1 for _, login in accounts}
                assert wire.peak <= 2
