"""Consumer cursor/reference/consent guards over actual native stdio and HTTP."""

import sys

import anyio
import pytest
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client

from tests_native.errors import closed
from tests_native.published_schema import assert_matches_published_schema
from tests_native.test_native_stdio import server_process
from tests_native.wire import Wire


@pytest.mark.asyncio
async def test_window_cursor_rejects_wrong_query_account_and_changed_source():
    async with Wire().serve() as wire:
        with anyio.fail_after(30):
            async with (
                stdio_client(
                    server_process(wire.origin, [("first", "login"), ("second", "other")]),
                    errlog=sys.stderr,
                ) as streams,
                ClientSession(*streams) as session,
            ):
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
                    assert bad.is_error and closed(bad.structured_content) == {
                        "error": {"code": "INVALID_INPUT"}
                    }
                    assert len(wire.calls) == calls
                # The synthetic source has exactly two dated grades. A cursor
                # at its end must reject, not masquerade as an empty last page.
                past_end = await session.call_tool(
                    "get_grades_window", query | {"cursor": cursor | {"offset": 2}}
                )
                assert past_end.is_error and closed(past_end.structured_content) == {
                    "error": {"code": "STALE_CURSOR"}
                }
                second = await session.call_tool("get_grades_window", query | {"cursor": cursor})
                assert not second.is_error
                assert second.structured_content["items"][0]["raw"] == "3"
                assert second.structured_content["pagination"]["next_cursor"] is None
                assert second.structured_content["pagination"]["truncated"] is False
                assert second.structured_content["pagination"]["reason"] is None
                wire.grade_suffix = "2"
                stale = await session.call_tool("get_grades_window", query | {"cursor": cursor})
                assert stale.is_error and closed(stale.structured_content) == {
                    "error": {"code": "STALE_CURSOR"}
                }


@pytest.mark.asyncio
async def test_reference_backend_context_and_mark_read_guards_are_preflight_only():
    async with Wire().serve() as wire:
        with anyio.fail_after(20):
            async with (
                stdio_client(
                    server_process(wire.origin, [("account", "login")]), errlog=sys.stderr
                ) as streams,
                ClientSession(*streams) as session,
            ):
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
                for ref, consent, error in (
                    (
                        message,
                        False,
                        {"code": "CONSENT_REQUIRED", "requires": "allow_mark_read"},
                    ),
                    (message | {"backend": "legacy"}, False, {"code": "INVALID_INPUT"}),
                    (message | {"backend": "legacy"}, True, {"code": "INVALID_INPUT"}),
                ):
                    result = await session.call_tool(
                        "get_message_content",
                        {
                            "account_alias": "account",
                            "message_ref": ref,
                            "allow_mark_read": consent,
                        },
                    )
                    assert result.is_error and closed(result.structured_content) == {"error": error}
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
                assert result.is_error and closed(result.structured_content) == {
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
                assert result.is_error and closed(result.structured_content) == {
                    "error": {"code": "UNSUPPORTED_CAPABILITY"}
                }
                assert len(wire.calls) == calls


@pytest.mark.asyncio
async def test_shared_host_budget_cannot_be_reset_by_another_tool_call():
    async with Wire().serve() as wire:
        with anyio.fail_after(20):
            async with (
                stdio_client(
                    server_process(wire.origin, [("account", "login")], budget_requests=1),
                    errlog=sys.stderr,
                ) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                for tool in ("get_student_information", "get_grades", "get_messages"):
                    result = await session.call_tool(tool, {"account_alias": "account"})
                    assert result.is_error and closed(result.structured_content) == {
                        "error": {"code": "LIMIT"}
                    }
                assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_invalid_calendar_date_and_collection_inputs_never_authenticate():
    async with Wire().serve() as wire:
        with anyio.fail_after(20):
            async with (
                stdio_client(
                    server_process(wire.origin, [("account", "login")]), errlog=sys.stderr
                ) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                cases = [
                    ("get_homework", {"date_from": "2026-10-05"}),
                    ("get_grades_window", {"date_from": 0}),
                    ("get_timetable", {"monday": "2026-02-30"}),
                    ("get_agenda", {"year": 2026, "month": True}),
                    (
                        "get_completed_lessons",
                        {"date_from": "2026-10-06", "date_to": "2026-10-05"},
                    ),
                    ("get_messages", {"limit": True}),
                ]
                for name, arguments in cases:
                    result = await session.call_tool(name, {"account_alias": "account"} | arguments)
                    assert result.is_error and closed(result.structured_content) == {
                        "error": {"code": "INVALID_INPUT"}
                    }
                assert wire.calls == []


@pytest.mark.asyncio
async def test_whole_grade_and_attendance_reads_are_paged_with_bound_cursors():
    async with Wire().serve() as wire:
        with anyio.fail_after(30):
            async with (
                stdio_client(
                    server_process(wire.origin, [("first", "login")]), errlog=sys.stderr
                ) as streams,
                ClientSession(*streams) as session,
            ):
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
                assert closed(bad.structured_content) == {"error": {"code": "INVALID_INPUT"}}


@pytest.mark.asyncio
async def test_announcements_at_the_api_text_maximum_are_returned_page_by_page():
    # #90: the API accepts a 256 KiB page with up to 262144 characters of text.
    # A quote costs 2 bytes in structuredContent and 4 in the escaped text copy,
    # so these four notices (about 960 KiB returned at once) were a LIMIT.
    text = 'a"' * 30000
    notices = [(f"Ogłoszenie {index}", f"{index}{text}") for index in range(4)]
    wire = Wire()
    wire.announcements = notices
    async with wire.serve():
        with anyio.fail_after(60):
            async with (
                stdio_client(
                    server_process(wire.origin, [("first", "login"), ("second", "other")]),
                    errlog=sys.stderr,
                ) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                query = {"account_alias": "first"}
                contents, reasons, cursor = [], [], None
                while True:
                    result = await session.call_tool(
                        "get_announcements", query | ({"cursor": cursor} if cursor else {})
                    )
                    assert not result.is_error, result.structured_content
                    await assert_matches_published_schema(session, "get_announcements", result)
                    assert len(result.model_dump_json(by_alias=True).encode()) <= 512 * 1024
                    page = result.structured_content
                    contents += [item["content"] for item in page["items"]]
                    reasons.append(page["pagination"]["reason"])
                    cursor = page["pagination"]["next_cursor"]
                    if cursor is None:
                        break
                    assert page["pagination"]["truncated"] is True
                    calls = len(wire.calls)
                    other = await session.call_tool(
                        "get_announcements", {"account_alias": "second", "cursor": cursor}
                    )
                    assert other.is_error and closed(other.structured_content) == {
                        "error": {"code": "INVALID_INPUT"}
                    }
                    assert len(wire.calls) == calls
                assert contents == [content for _, content in notices]
                assert reasons == ["size_limit", None]
                # Short texts page by limit; a changed collection is stale.
                wire.announcements = [(f"Short {i}", f"Short text {i}") for i in range(3)]
                first = await session.call_tool("get_announcements", query | {"limit": 2})
                page = first.structured_content
                assert [item["title"] for item in page["items"]] == ["Short 0", "Short 1"]
                assert page["pagination"]["reason"] == "item_limit"
                cursor = page["pagination"]["next_cursor"]
                rest = await session.call_tool(
                    "get_announcements", query | {"limit": 2, "cursor": cursor}
                )
                assert [item["title"] for item in rest.structured_content["items"]] == ["Short 2"]
                assert rest.structured_content["pagination"] == {
                    "next_cursor": None,
                    "truncated": False,
                    "reason": None,
                    "consistency": "best_effort",
                }
                wire.announcements = wire.announcements[1:]
                stale = await session.call_tool(
                    "get_announcements", query | {"limit": 2, "cursor": cursor}
                )
                assert stale.is_error and closed(stale.structured_content) == {
                    "error": {"code": "STALE_CURSOR"}
                }


def test_sized_page_edges_an_empty_collection_and_an_oversized_first_item():
    from librus_python_api.exceptions import LibrusError

    from librus_mcp import presentation
    from librus_mcp.presentation import sized_page, window_page

    context = "a" * 64
    selected, pagination = sized_page((), context=context, query=("q",), cursor=None, limit=5)
    assert selected == () and pagination.next_cursor is None and pagination.reason is None
    items = ("x" * 300, "y", "z")
    # An item over the whole budget still comes alone, so its cursor moves on.
    selected, pagination = sized_page(
        items, context=context, query=("q",), cursor=None, limit=5, max_bytes=100
    )
    assert selected == ("x" * 300,) and pagination.reason == "size_limit"
    assert pagination.next_cursor is not None and pagination.next_cursor.offset == 1
    rest, last = sized_page(
        items, context=context, query=("q",), cursor=pagination.next_cursor, limit=5
    )
    assert rest == ("y", "z") and last.next_cursor is None
    # The same source digest as window_page, so the one-pass encoding is exact.
    _, window = window_page(items, context=context, query=("q",), cursor=None, limit=1)
    assert window.next_cursor is not None
    assert window.next_cursor.source == pagination.next_cursor.source
    # The cap is read when a page is built, as the server reads it.
    original = presentation.MAX_RESULT_BYTES
    try:
        presentation.MAX_RESULT_BYTES = presentation._ENVELOPE_RESERVE + 10
        small, capped = sized_page(items, context=context, query=("q",), cursor=None, limit=5)
        assert small == ("x" * 300,) and capped.reason == "size_limit"
    finally:
        presentation.MAX_RESULT_BYTES = original
    try:
        sized_page(items[1:], context=context, query=("q",), cursor=pagination.next_cursor, limit=5)
    except LibrusError as error:
        assert error.kind.value == "stale_cursor"
    else:
        raise AssertionError("a cursor for another source was accepted")
