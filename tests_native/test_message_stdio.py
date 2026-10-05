"""Original offline modern mailbox/directory proof at the consumer wire boundary."""

import anyio
import pytest
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client

from tests_native.test_native_stdio import server_process
from tests_native.wire import Wire


@pytest.mark.asyncio
async def test_modern_paging_content_consent_directory_and_context_binding():
    async with Wire().serve() as wire:
        with anyio.fail_after(30):
            async with stdio_client(
                server_process(wire.origin, [("first", "71"), ("second", "72")])
            ) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    base = {"account_alias": "first"}
                    query = base | {"limit": 1, "max_pages": 1, "page_size": 2}
                    listed = await session.call_tool("get_messages", query)
                    assert not listed.is_error
                    payload = listed.structured_content
                    assert payload["backend"] == "modern"
                    assert payload["items"][0]["summary"]["subject"] == "Fixture subject 81 for 71"
                    cursor = payload["pagination"]["next_cursor"]
                    assert cursor["backend"] == "modern"
                    assert cursor["offset"] == 1
                    calls = len(wire.calls)
                    for changes in ({"account_alias": "second"}, {"folder": "sent"}):
                        bad = await session.call_tool(
                            "get_messages", query | {"cursor": cursor} | changes
                        )
                        assert bad.is_error and bad.structured_content == {
                            "error": {"code": "INVALID_INPUT"}
                        }
                        assert len(wire.calls) == calls
                    continued = await session.call_tool("get_messages", query | {"cursor": cursor})
                    assert not continued.is_error
                    assert (
                        continued.structured_content["items"][0]["reference"]["identifier"] == "82"
                    )
                    reference = payload["items"][0]["reference"]
                    calls = len(wire.calls)
                    rejected = await session.call_tool(
                        "get_message_content", base | {"message_ref": reference}
                    )
                    assert rejected.is_error and rejected.structured_content == {
                        "error": {"code": "INVALID_INPUT"}
                    }
                    assert len(wire.calls) == calls
                    opened = await session.call_tool(
                        "get_message_content",
                        base | {"message_ref": reference, "allow_mark_read": True},
                    )
                    assert not opened.is_error
                    assert opened.structured_content["data"]["text"] == "Fixture body"
                    assert sum(path == "/api/inbox/messages/81" for _, path, _ in wire.calls) == 1
                    sent = await session.call_tool(
                        "get_messages", base | {"folder": "sent", "limit": 1, "max_pages": 1}
                    )
                    assert not sent.is_error
                    content = await session.call_tool(
                        "get_message_content",
                        base | {"message_ref": sent.structured_content["items"][0]["reference"]},
                    )
                    assert not content.is_error
                    assert content.structured_content["data"]["summary"]["unread"] is None
                    types = await session.call_tool("get_recipient_types", base)
                    assert not types.is_error
                    selected = types.structured_content["items"][0]["reference"]
                    recipients = await session.call_tool(
                        "get_recipients", base | {"recipient_type": selected}
                    )
                    assert not recipients.is_error
                    assert recipients.structured_content["items"][0]["label"] == "Fixture Teacher"
                    calls = len(wire.calls)
                    choices = await session.call_tool(
                        "get_recipient_choices", base | {"recipient_type": selected}
                    )
                    assert choices.is_error and choices.structured_content == {
                        "error": {"code": "UNSUPPORTED_CAPABILITY"}
                    }
                    assert len(wire.calls) == calls
                    other = await session.call_tool(
                        "get_messages", {"account_alias": "second", "limit": 1, "max_pages": 1}
                    )
                    assert not other.is_error
                    assert (
                        other.structured_content["items"][0]["summary"]["subject"]
                        == "Fixture subject 81 for 72"
                    )
                    assert (
                        other.structured_content["items"][0]["reference"]["context"]
                        != reference["context"]
                    )
                    assert wire.logins == {"71": 1, "72": 1}
