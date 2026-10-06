"""Consumer cursor/reference/consent guards over actual native stdio and HTTP."""

import sys

import anyio
import pytest
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client

from tests_native.test_native_stdio import server_process
from tests_native.wire import Wire


@pytest.mark.asyncio
async def test_window_cursor_rejects_wrong_query_account_and_changed_source():
    async with Wire().serve() as wire:
        with anyio.fail_after(30):
            async with stdio_client(
                server_process(wire.origin, [("first", "login"), ("second", "other")]),
                errlog=sys.stderr,
            ) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    query = {
                        "account_alias": "first",
                        "date_from": "2026-09-24",
                        "date_to": "2026-09-25",
                        "limit": 1,
                    }
                    first = await session.call_tool("get_grades_window", query)
                    assert not first.is_error
                    assert first.structured_content["items"][0]["raw"] == "4+"
                    cursor = first.structured_content["pagination"]["next_cursor"]
                    assert cursor is not None
                    assert first.structured_content["pagination"]["truncated"] is True
                    assert first.structured_content["pagination"]["reason"] == "item_limit"
                    calls = len(wire.calls)
                    for changed in (
                        {"date_from": "2026-09-25"},
                        {"account_alias": "second"},
                        {"scope": "week"},
                    ):
                        bad = await session.call_tool(
                            "get_grades_window", query | {"cursor": cursor} | changed
                        )
                        assert bad.is_error and bad.structured_content == {
                            "error": {"code": "INVALID_INPUT"}
                        }
                        assert len(wire.calls) == calls
                    # The synthetic source has exactly two dated grades. A cursor
                    # at its end must reject, not masquerade as an empty last page.
                    past_end = await session.call_tool(
                        "get_grades_window", query | {"cursor": cursor | {"offset": 2}}
                    )
                    assert past_end.is_error and past_end.structured_content == {
                        "error": {"code": "STALE_CURSOR"}
                    }
                    second = await session.call_tool(
                        "get_grades_window", query | {"cursor": cursor}
                    )
                    assert not second.is_error
                    assert second.structured_content["items"][0]["raw"] == "3"
                    assert second.structured_content["pagination"]["next_cursor"] is None
                    assert second.structured_content["pagination"]["truncated"] is False
                    assert second.structured_content["pagination"]["reason"] is None
                    wire.grade_suffix = "2"
                    stale = await session.call_tool("get_grades_window", query | {"cursor": cursor})
                    assert stale.is_error and stale.structured_content == {
                        "error": {"code": "STALE_CURSOR"}
                    }


@pytest.mark.asyncio
async def test_reference_backend_context_and_mark_read_guards_are_preflight_only():
    async with Wire().serve() as wire:
        with anyio.fail_after(20):
            async with stdio_client(
                server_process(wire.origin, [("account", "login")]), errlog=sys.stderr
            ) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    # Obtain an actual context from a bound presentation cursor.
                    window = await session.call_tool(
                        "get_grades_window", {"account_alias": "account", "limit": 1}
                    )
                    context = window.structured_content["pagination"]["next_cursor"]["context"]
                    calls = len(wire.calls)
                    message = {
                        "context": context,
                        "backend": "modern",
                        "folder": "received",
                        "identifier": "19",
                        "account": "account",
                    }
                    # Binding failures must not be hidden by missing consent.
                    # Independent account/context mutations are covered with
                    # actual message references in test_message_stdio.py.
                    for ref, consent in (
                        (message, False),
                        (message | {"backend": "legacy"}, True),
                    ):
                        result = await session.call_tool(
                            "get_message_content",
                            {
                                "account_alias": "account",
                                "message_ref": ref,
                                "allow_mark_read": consent,
                            },
                        )
                        assert result.is_error and result.structured_content == {
                            "error": {"code": "INVALID_INPUT"}
                        }
                        assert len(wire.calls) == calls
                    school = {
                        "context": context,
                        "kind": "agenda",
                        "identifier": "23",
                        "account": "account",
                    }
                    result = await session.call_tool(
                        "get_homework_detail", {"account_alias": "account", "homework_ref": school}
                    )
                    assert result.is_error and result.structured_content == {
                        "error": {"code": "INVALID_INPUT"}
                    }
                    assert len(wire.calls) == calls
                    selection = {
                        "context": context,
                        "backend": "modern",
                        "account": "account",
                        "identifier": "students",
                    }
                    result = await session.call_tool(
                        "get_recipient_choices",
                        {"account_alias": "account", "recipient_type": selection},
                    )
                    assert result.is_error and result.structured_content == {
                        "error": {"code": "UNSUPPORTED_CAPABILITY"}
                    }
                    assert len(wire.calls) == calls


@pytest.mark.asyncio
async def test_shared_host_budget_cannot_be_reset_by_another_tool_call():
    async with Wire().serve() as wire:
        with anyio.fail_after(20):
            async with stdio_client(
                server_process(wire.origin, [("account", "login")], budget_requests=1),
                errlog=sys.stderr,
            ) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    for tool in ("get_student_information", "get_grades", "get_messages"):
                        result = await session.call_tool(tool, {"account_alias": "account"})
                        assert result.is_error and result.structured_content == {
                            "error": {"code": "LIMIT"}
                        }
                    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_invalid_calendar_date_and_collection_inputs_never_authenticate():
    async with Wire().serve() as wire:
        with anyio.fail_after(20):
            async with stdio_client(
                server_process(wire.origin, [("account", "login")]), errlog=sys.stderr
            ) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    cases = [
                        ("get_homework", {"date_from": "2026-10-05"}),
                        ("get_grades_window", {"date_from": 0}),
                        ("get_timetable", {"monday": "2026-10-06"}),
                        ("get_agenda", {"year": 2026, "month": True}),
                        (
                            "get_completed_lessons",
                            {"date_from": "2026-10-06", "date_to": "2026-10-05"},
                        ),
                        ("get_messages", {"limit": True}),
                    ]
                    for name, arguments in cases:
                        result = await session.call_tool(
                            name, {"account_alias": "account"} | arguments
                        )
                        assert result.is_error and result.structured_content == {
                            "error": {"code": "INVALID_INPUT"}
                        }
                    assert wire.calls == []


@pytest.mark.asyncio
async def test_whole_grade_and_attendance_reads_are_paged_with_bound_cursors():
    async with Wire().serve() as wire:
        with anyio.fail_after(30):
            async with stdio_client(
                server_process(wire.origin, [("first", "login")]), errlog=sys.stderr
            ) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    for tool in ("get_grades", "get_attendance"):
                        query = {"account_alias": "first", "limit": 1}
                        whole = await session.call_tool(tool, {"account_alias": "first"})
                        assert not whole.is_error
                        total = whole.structured_content["items"]
                        assert len(total) >= (2 if tool == "get_grades" else 1)
                        assert whole.structured_content["pagination"]["truncated"] is False
                        seen = []
                        cursor = None
                        while True:
                            page = await session.call_tool(
                                tool, query | ({"cursor": cursor} if cursor else {})
                            )
                            assert not page.is_error
                            content = page.structured_content
                            if tool == "get_grades":
                                assert content["averages"] == whole.structured_content["averages"]
                            seen.extend(content["items"])
                            cursor = content["pagination"]["next_cursor"]
                            if cursor is None:
                                break
                            assert content["pagination"]["reason"] == "item_limit"
                        assert seen == total
                    # A cursor is bound to its tool query, not reusable elsewhere.
                    first = await session.call_tool(
                        "get_grades", {"account_alias": "first", "limit": 1}
                    )
                    cursor = first.structured_content["pagination"]["next_cursor"]
                    assert cursor is not None
                    bad = await session.call_tool(
                        "get_attendance", {"account_alias": "first", "limit": 1, "cursor": cursor}
                    )
                    assert bad.structured_content == {"error": {"code": "INVALID_INPUT"}}
