"""Real MCP durable claims over native SQLite/HTTP, including process restart."""

import anyio
import pytest
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client

from tests_native.test_native_stdio import server_process
from tests_native.wire import Wire


async def discover_message(session):
    types = await session.call_tool("get_recipient_types", {"account_alias": "sender"})
    assert not types.is_error
    recipients = await session.call_tool(
        "get_recipients",
        {
            "account_alias": "sender",
            "recipient_type": types.structured_content["items"][0]["reference"],
        },
    )
    assert not recipients.is_error
    data = recipients.structured_content
    return {
        "recipients": [
            data["items"][0]["reference"]
            | {
                "backend": data["backend"],
                "context": data["context"],
            }
        ],
        "subject": "Fixture subject",
        "body": "Fixture plain body",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", [False, True])
async def test_preview_binding_claim_outcome_and_restart_never_replays_send(tmp_path, unknown):
    async with Wire().serve() as wire:
        wire.send_unknown = unknown
        process = server_process(
            wire.origin,
            [("sender", "71"), ("other", "72")],
            features={"send_message": True},
            state_dir=tmp_path / "state",
        )
        with anyio.fail_after(45):
            async with stdio_client(process) as streams, ClientSession(*streams) as session:
                await session.initialize()
                message = await discover_message(session)
                arguments = {"account_alias": "sender", "message": message}
                calls = len(wire.calls)
                preview = await session.call_tool("preview_message", arguments)
                assert not preview.is_error
                assert preview.structured_content["message"] == message
                assert len(wire.calls) == calls
                token = preview.structured_content["confirmation_token"]
                no_consent = await session.call_tool(
                    "send_message", arguments | {"confirmation_token": token}
                )
                assert no_consent.is_error and no_consent.structured_content == {
                    "error": {"code": "INVALID_INPUT"}
                }
                assert len(wire.calls) == calls
                changed = await session.call_tool(
                    "send_message",
                    arguments
                    | {
                        "message": message | {"body": "Changed body"},
                        "confirmation_token": token,
                        "confirm": True,
                    },
                )
                assert changed.is_error and changed.structured_content == {
                    "error": {"code": "INVALID_INPUT"}
                }
                assert len(wire.calls) == calls
                invalidated = await session.call_tool(
                    "get_send_outcome", {"account_alias": "sender", "confirmation_token": token}
                )
                assert invalidated.structured_content["data"]["phase"] == "invalidated"
                preview = await session.call_tool("preview_message", arguments)
                assert not preview.is_error
                token = preview.structured_content["confirmation_token"]
            # New process reconstructs the approved immutable attempt from supplied
            # references, not a memory token dictionary or a persisted body.
            async with stdio_client(process) as streams, ClientSession(*streams) as session:
                await session.initialize()
                sent = await session.call_tool(
                    "send_message", arguments | {"confirmation_token": token, "confirm": True}
                )
                assert not sent.is_error
                expected = "unknown" if unknown else "accepted"
                assert sent.structured_content["data"]["status"] == expected
                assert sent.structured_content["durable"]["requires_reconciliation"] is unknown
                assert len(wire.sent_payloads) == 1
                calls = len(wire.calls)
                replay = await session.call_tool(
                    "send_message", arguments | {"confirmation_token": token, "confirm": True}
                )
                assert replay.is_error and replay.structured_content == {
                    "error": {"code": "INVALID_INPUT"}
                }
                duplicate = await session.call_tool("preview_message", arguments)
                assert duplicate.is_error and duplicate.structured_content == {
                    "error": {"code": "UNKNOWN_DELIVERY"}
                }
                assert len(wire.calls) == calls
            async with stdio_client(process) as streams, ClientSession(*streams) as session:
                await session.initialize()
                calls = len(wire.calls)
                outcome = await session.call_tool(
                    "get_send_outcome", {"account_alias": "sender", "confirmation_token": token}
                )
                assert (
                    not outcome.is_error and outcome.structured_content["data"]["phase"] == expected
                )
                history = await session.call_tool("get_send_history", {"account_alias": "sender"})
                assert {
                    item["outcome"]["phase"] for item in history.structured_content["items"]
                } == {"invalidated", expected}
                foreign = await session.call_tool(
                    "get_send_outcome", {"account_alias": "other", "confirmation_token": token}
                )
                assert foreign.is_error and foreign.structured_content == {
                    "error": {"code": "INVALID_INPUT"}
                }
                assert len(wire.calls) == calls
                assert len(wire.sent_payloads) == 1
        # Raw byte checks prove no plaintext at rest without depending on SQL layout.
        for path in (tmp_path / "state" / "native-v2").iterdir():
            if path.is_file():
                body = path.read_bytes()
                assert token.encode() not in body
                assert b"Fixture plain body" not in body
