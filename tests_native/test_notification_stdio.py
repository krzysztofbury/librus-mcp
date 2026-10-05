"""Native durable replay/ack over real MCP and SQLite, never live consumption."""

import anyio
import pytest
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client

from tests_native.test_native_stdio import server_process
from tests_native.wire import Wire


@pytest.mark.asyncio
async def test_notification_consent_restart_exact_replay_ack_and_account_isolation(tmp_path):
    async with Wire().serve() as wire:
        process = server_process(
            wire.origin,
            [("first", "71"), ("second", "72")],
            features={"notifications": True},
            state_dir=tmp_path / "state",
        )
        with anyio.fail_after(30):
            async with stdio_client(process) as streams, ClientSession(*streams) as session:
                await session.initialize()
                status = await session.call_tool(
                    "get_notification_status", {"account_alias": "first"}
                )
                assert not status.is_error and not status.structured_content["has_pending_work"]
                assert wire.calls == []
                for categories in (["grades", "agenda"], ["messages", "messages"]):
                    rejected = await session.call_tool(
                        "get_new_notifications",
                        {"account_alias": "first", "categories": categories},
                    )
                    assert rejected.is_error and rejected.structured_content == {
                        "error": {"code": "INVALID_INPUT"}
                    }
                    assert wire.calls == []
                query = {"account_alias": "first", "categories": ["messages", "grades"]}
                batch = await session.call_tool("get_new_notifications", query)
                assert not batch.is_error, batch
                payload = batch.structured_content
                assert (
                    payload["data"]["first_run"] and payload["data"]["messages_backend"] == "modern"
                )
                assert {item["category"] for item in payload["data"]["items"]} == {
                    "messages",
                    "grades",
                }
                assert len(payload["data"]["items"]) == 5
                assert all(item["provenance"] == "observed" for item in payload["data"]["items"])
                assert not any(path.startswith("/api/inbox/messages/") for _, path, _ in wire.calls)
            async with stdio_client(process) as streams, ClientSession(*streams) as session:
                await session.initialize()
                calls = len(wire.calls)
                replay = await session.call_tool("get_new_notifications", query)
                assert not replay.is_error and replay.structured_content == payload
                status = await session.call_tool(
                    "get_notification_status", {"account_alias": "first"}
                )
                assert (
                    status.structured_content["has_pending_work"]
                    and not status.structured_content["data"]["initialized"]
                )
                assert status.structured_content["data"]["pending"]["item_count"] == 5
                reordered = await session.call_tool(
                    "get_new_notifications", query | {"categories": ["grades", "messages"]}
                )
                assert reordered.is_error
                context = payload["data"]["context"]["identifier"]
                receipt = payload["data"]["receipt"]
                ack = {"account_alias": "first", "context": context, "receipt": receipt}
                foreign = await session.call_tool(
                    "acknowledge_notifications", ack | {"account_alias": "second"}
                )
                assert foreign.is_error and foreign.structured_content == {
                    "error": {"code": "INVALID_INPUT"}
                }
                assert len(wire.calls) == calls
                for _ in range(2):
                    accepted = await session.call_tool("acknowledge_notifications", ack)
                    assert not accepted.is_error and accepted.structured_content["acknowledged"]
                assert len(wire.calls) == calls
            async with stdio_client(process) as streams, ClientSession(*streams) as session:
                await session.initialize()
                calls = len(wire.calls)
                status = await session.call_tool(
                    "get_notification_status", {"account_alias": "first"}
                )
                assert (
                    not status.structured_content["has_pending_work"]
                    and status.structured_content["data"]["initialized"]
                )
                assert status.structured_content["data"]["last_acknowledged_receipt"] == receipt
                assert len(wire.calls) == calls
                diff = await session.call_tool("get_new_notifications", query)
                assert not diff.is_error and diff.structured_content["data"]["items"] == []
                assert diff.structured_content["data"]["first_run"] is False
                other = await session.call_tool(
                    "get_new_notifications", query | {"account_alias": "second"}
                )
                assert not other.is_error and other.structured_content["data"]["first_run"]
                assert len(other.structured_content["data"]["items"]) == 5


@pytest.mark.asyncio
async def test_legacy_state_quarantines_poll_not_other_accounts_or_academic_reads(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    source = state / "old.notifications.json"
    source.write_bytes(b"malformed old state, do not overwrite")
    source.chmod(0o600)
    async with Wire().serve() as wire:
        process = server_process(
            wire.origin,
            [("old", "71"), ("new", "72")],
            features={"notifications": True},
            state_dir=state,
        )
        with anyio.fail_after(20):
            async with stdio_client(process) as streams, ClientSession(*streams) as session:
                await session.initialize()
                blocked = await session.call_tool(
                    "get_new_notifications", {"account_alias": "old", "categories": ["grades"]}
                )
                assert blocked.is_error and blocked.structured_content == {
                    "error": {"code": "STORAGE"}
                }
                assert (
                    wire.calls == []
                    and source.read_bytes() == b"malformed old state, do not overwrite"
                )
                academic = await session.call_tool(
                    "get_student_information", {"account_alias": "old"}
                )
                assert not academic.is_error
                other = await session.call_tool(
                    "get_new_notifications", {"account_alias": "new", "categories": ["grades"]}
                )
                assert not other.is_error and len(other.structured_content["data"]["items"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [False, True])
async def test_consumed_checkpoint_replays_or_stays_quarantined_without_second_consume(
    tmp_path, malformed
):
    async with Wire().serve() as wire:
        wire.schedule_malformed = malformed
        process = server_process(
            wire.origin,
            [("account", "71")],
            features={"notifications": True},
            state_dir=tmp_path / "state",
        )
        query = {"account_alias": "account", "categories": ["agenda"]}
        with anyio.fail_after(30):
            async with stdio_client(process) as streams, ClientSession(*streams) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_new_notifications", query | {"allow_consume_events": True}
                )
                if malformed:
                    assert result.is_error and result.structured_content == {
                        "error": {"code": "PARSE"}
                    }
                else:
                    assert (
                        not result.is_error and len(result.structured_content["data"]["items"]) == 1
                    )
                    batch = result.structured_content
                assert (
                    sum(
                        path == "/terminarz/dodane_od_ostatniego_logowania"
                        for _, path, _ in wire.calls
                    )
                    == 1
                )
            async with stdio_client(process) as streams, ClientSession(*streams) as session:
                await session.initialize()
                calls = len(wire.calls)
                status = await session.call_tool(
                    "get_notification_status", {"account_alias": "account"}
                )
                assert not status.is_error and status.structured_content["has_pending_work"]
                assert status.structured_content["data"]["raw"]["wire_bytes"] > 0
                assert status.structured_content["data"]["uncertain_consume"] is False
                replay = await session.call_tool("get_new_notifications", query)
                if malformed:
                    assert replay.is_error and replay.structured_content == {
                        "error": {"code": "PARSE"}
                    }
                    retry = await session.call_tool(
                        "get_new_notifications", query | {"allow_consume_events": True}
                    )
                    assert retry.is_error and retry.structured_content == replay.structured_content
                else:
                    assert not replay.is_error and replay.structured_content == batch
                    acknowledged = await session.call_tool(
                        "acknowledge_notifications",
                        {
                            "account_alias": "account",
                            "context": batch["data"]["context"]["identifier"],
                            "receipt": batch["data"]["receipt"],
                        },
                    )
                    assert not acknowledged.is_error
                    status = await session.call_tool(
                        "get_notification_status", {"account_alias": "account"}
                    )
                    assert not status.structured_content["has_pending_work"]
                assert len(wire.calls) == calls
