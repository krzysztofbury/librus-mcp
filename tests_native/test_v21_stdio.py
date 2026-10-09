"""2.1 contracts over MCP stdio, the installed API and original loopback inputs."""

from contextlib import AsyncExitStack

import anyio
import pytest
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client

from tests_native.published_schema import assert_matches_published_schema
from tests_native.test_native_stdio import server_process
from tests_native.wire import Wire


@pytest.mark.asyncio
async def test_formative_grades_share_paging_dates_and_source_binding():
    async with Wire().serve() as wire:
        wire.formative = True
        with anyio.fail_after(30):
            async with stdio_client(server_process(wire.origin, [("first", "71")])) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    for tool in ("get_grades", "get_grades_window"):
                        query = {"account_alias": "first", "limit": 2}
                        first = await session.call_tool(tool, query)
                        assert not first.is_error, first
                        assert first.structured_content["items"][0]["formative_id"] == "401"
                        cursor = first.structured_content["pagination"]["next_cursor"]
                        assert cursor is not None
                        last = await session.call_tool(tool, query | {"cursor": cursor})
                        assert not last.is_error, last
                        await assert_matches_published_schema(session, tool, last)
                        assert last.structured_content["items"] == [
                            {
                                "record_type": "formative",
                                "assessment": {
                                    "subject": "KARTA SPOSTRZEŻEŃ",
                                    "text": wire.formative_text,
                                    "category": "Fixture development",
                                    "semester": 1,
                                    "day": "2026-09-25",
                                    "assessment_type": "Fixture assessment",
                                    "detail_id": "401",
                                },
                            }
                        ]
                        assert last.structured_content["pagination"]["next_cursor"] is None
                        wire.formative_text += " changed"
                        stale = await session.call_tool(tool, query | {"cursor": cursor})
                        assert stale.structured_content == {"error": {"code": "STALE_CURSOR"}}
                    dated = await session.call_tool(
                        "get_grades_window",
                        {
                            "account_alias": "first",
                            "date_from": "2026-09-24",
                            "date_to": "2026-09-24",
                        },
                    )
                    assert not dated.is_error
                    assert [item["record_type"] for item in dated.structured_content["items"]] == [
                        "numeric"
                    ]
                    assert not any("/szczegoly/" in path for _, path, _ in wire.calls)


@pytest.mark.asyncio
async def test_new_school_and_directory_reads_page_without_losing_native_fields():
    async with Wire().serve() as wire:
        with anyio.fail_after(40):
            async with stdio_client(
                server_process(wire.origin, [("first", "71"), ("second", "72")])
            ) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    pages = {}
                    for tool in (
                        "get_school_year_archive",
                        "get_class_free_days",
                        "get_message_correspondents",
                        "get_teacher_subjects",
                    ):
                        query = {"account_alias": "first", "limit": 1}
                        first = await session.call_tool(tool, query)
                        assert not first.is_error, first
                        await assert_matches_published_schema(session, tool, first)
                        cursor = first.structured_content["pagination"]["next_cursor"]
                        assert cursor is not None
                        calls = len(wire.calls)
                        bad = await session.call_tool(
                            tool, query | {"account_alias": "second", "cursor": cursor}
                        )
                        assert bad.structured_content == {"error": {"code": "INVALID_INPUT"}}
                        assert len(wire.calls) == calls
                        last = await session.call_tool(tool, query | {"cursor": cursor})
                        assert not last.is_error, last
                        await assert_matches_published_schema(session, tool, last)
                        assert last.structured_content["pagination"]["next_cursor"] is None
                        pages[tool] = (
                            first.structured_content["items"] + last.structured_content["items"]
                        )
                    year, achievement = pages["get_school_year_archive"]
                    assert (
                        year["record_type"] == "year"
                        and achievement["record_type"] == "achievement"
                    )
                    assert year["data"]["subjects"][0]["marks"] == {
                        "first_semester": "",
                        "second_semester": "-",
                        "year_end": "5",
                    }
                    assert year["data"]["descriptive"][0]["text"] == "First line\nSecond line"
                    assert year["data"]["absences"]["excused"]["year_end"] == 9
                    free = pages["get_class_free_days"]
                    assert free[0]["date_to"] == "2026-10-13" and free[0]["lesson_no_from"] is None
                    assert (free[1]["lesson_no_from"], free[1]["lesson_no_to"]) == (2, 4)
                    assert [item["subject"] for item in pages["get_teacher_subjects"]] == [
                        "Fixture Science",
                        "Fixture Writing",
                    ]
                    wire.history_empty = True
                    for tool in ("get_school_year_archive", "get_class_free_days"):
                        empty = await session.call_tool(tool, {"account_alias": "first"})
                        assert not empty.is_error and empty.structured_content["items"] == []
                    counts = await session.call_tool(
                        "get_message_unread_counts", {"account_alias": "first"}
                    )
                    assert not counts.is_error, counts
                    await assert_matches_published_schema(
                        session, "get_message_unread_counts", counts
                    )
                    assert counts.structured_content["data"]["current"]["inbox"] == 0
                    assert counts.structured_content["data"]["archive"]["inbox"] == 10
                    assert not any("/messages/8" in path for _, path, _ in wire.calls)


@pytest.mark.asyncio
async def test_archive_filters_cursor_roundtrip_and_preflight_binding():
    async with Wire().serve() as wire:
        with anyio.fail_after(40):
            accounts = [
                ("first", "71", "modern"),
                ("second", "72", "modern"),
                ("legacy", "73", "legacy"),
            ]
            async with AsyncExitStack() as stack:
                streams = await stack.enter_async_context(
                    stdio_client(server_process(wire.origin, accounts))
                )
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    base = {"account_alias": "first", "limit": 1, "max_pages": 1, "page_size": 2}
                    for folder in ("received", "sent"):
                        people = await session.call_tool(
                            "get_message_correspondents",
                            {"account_alias": "first", "folder": folder},
                        )
                        ref = people.structured_content["items"][0]["reference"]
                        query = base | {
                            "folder": folder,
                            "correspondent": ref,
                            "unread_only": folder == "received",
                        }
                        first = await session.call_tool("get_messages", query)
                        assert not first.is_error, first
                        cursor = first.structured_content["pagination"]["next_cursor"]
                        assert cursor["correspondent"] == "501" and cursor["unread_only"] == (
                            folder == "received"
                        )
                        assert first.structured_content["correspondent"] == ref
                        second = await session.call_tool("get_messages", query | {"cursor": cursor})
                        assert not second.is_error, second
                        assert (
                            second.structured_content["items"][0]["reference"]["identifier"] == "82"
                        )
                        await assert_matches_published_schema(session, "get_messages", second)
                        sent_query = wire.message_queries[-1][1]
                        assert (
                            sent_query["senderId" if folder == "received" else "receiverId"]
                            == "501"
                        )
                        assert (sent_query.get("unreadOnly") == "1") == (folder == "received")
                        calls = len(wire.calls)
                        for changes in (
                            {"account_alias": "second"},
                            {"archived": True},
                            {"correspondent": None},
                            {"correspondent": ref | {"context": "0" * 64}},
                            {
                                "correspondent": ref
                                | {"folder": "sent" if folder == "received" else "received"}
                            },
                        ):
                            bad = await session.call_tool(
                                "get_messages", query | {"cursor": cursor} | changes
                            )
                            assert bad.structured_content == {"error": {"code": "INVALID_INPUT"}}
                            assert len(wire.calls) == calls
                        archive_query = base | {"folder": folder, "archived": True}
                        archive = await session.call_tool("get_messages", archive_query)
                        assert not archive.is_error, archive
                        archived_ref = archive.structured_content["items"][0]["reference"]
                        assert archived_ref["archived"] is True
                        assert archive.structured_content["archiving_in_progress"] is True
                        continued = await session.call_tool(
                            "get_messages",
                            archive_query
                            | {"cursor": archive.structured_content["pagination"]["next_cursor"]},
                        )
                        assert (
                            not continued.is_error
                            and continued.structured_content["items"][0]["reference"]["identifier"]
                            == "82"
                        )
                        calls = len(wire.calls)
                        opened = await session.call_tool(
                            "get_message_content",
                            {
                                "account_alias": "first",
                                "message_ref": archived_ref,
                                "allow_mark_read": True,
                            },
                        )
                        assert opened.structured_content == {
                            "error": {"code": "UNSUPPORTED_CAPABILITY"}
                        }
                        assert len(wire.calls) == calls
                    calls = len(wire.calls)
                    for tool, arguments in (
                        ("get_messages", {"archived": True}),
                        ("get_messages", {"unread_only": True}),
                        ("get_message_correspondents", {}),
                        ("get_teacher_subjects", {}),
                        ("get_message_unread_counts", {}),
                    ):
                        unsupported = await session.call_tool(
                            tool, {"account_alias": "legacy"} | arguments
                        )
                        assert unsupported.structured_content == {
                            "error": {"code": "UNSUPPORTED_CAPABILITY"}
                        }
                        assert len(wire.calls) == calls
