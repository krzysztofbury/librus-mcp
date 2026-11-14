"""2.1 contracts over MCP stdio, the installed API and original loopback inputs."""

import importlib.util
from contextlib import AsyncExitStack
from datetime import date
from pathlib import Path

import anyio
import pytest
from librus_python_api import DescriptiveGrade, GradeCorrection, GradeView, NumericGrade
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client

from librus_mcp.schemas import grade_items
from tests_native.errors import closed
from tests_native.published_schema import assert_matches_published_schema
from tests_native.test_native_stdio import server_process
from tests_native.wire import Wire


@pytest.mark.asyncio
async def test_formative_grades_share_paging_dates_and_source_binding():
    async with Wire().serve() as wire:
        wire.formative = True
        with anyio.fail_after(30):
            async with (
                stdio_client(server_process(wire.origin, [("first", "71")])) as streams,
                ClientSession(*streams) as session,
            ):
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
                    assert closed(stale.structured_content) == {"error": {"code": "STALE_CURSOR"}}
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
async def test_grade_cursors_survive_librus_reordering_a_cell():
    # Observed live on 2026-11-06: one cell's grades came back in a different
    # order on each read, so every continuation was STALE_CURSOR.
    async with Wire().serve() as wire:
        wire.shuffle_grades = True
        with anyio.fail_after(30):
            async with (
                stdio_client(server_process(wire.origin, [("first", "71")])) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                for tool in ("get_grades", "get_grades_window"):
                    query = {"account_alias": "first", "limit": 1}
                    first = await session.call_tool(tool, query)
                    assert not first.is_error, first
                    cursor = first.structured_content["pagination"]["next_cursor"]
                    last = await session.call_tool(tool, query | {"cursor": cursor})
                    assert not last.is_error, last
                    raws = [
                        item["raw"]
                        for page in (first, last)
                        for item in page.structured_content["items"]
                    ]
                    assert raws == ["4+", "3"]
                assert wire.grade_reads >= 4


@pytest.mark.asyncio
async def test_grade_ids_and_the_all_views_correction_links():
    # #88: the all view brackets a corrected grade with its correction; the
    # week view shows both unbracketed, so links there are unknown, not none.
    async with Wire().serve() as wire:
        wire.corrections = True
        with anyio.fail_after(30):
            async with (
                stdio_client(server_process(wire.origin, [("first", "71")])) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()

                async def links(tool, **query):
                    result = await session.call_tool(tool, {"account_alias": "first"} | query)
                    assert not result.is_error, result
                    await assert_matches_published_schema(session, tool, result)
                    return [
                        (item["grade_id"], item["corrects"], item["corrected_by"])
                        for item in result.structured_content["items"]
                    ]

                for tool in ("get_grades", "get_grades_window"):
                    assert await links(tool) == [("301", [], ["302"]), ("302", ["301"], [])]
                    for scope in ("week", "last_login"):
                        assert await links(tool, scope=scope) == [
                            ("301", None, None),
                            ("302", None, None),
                        ]
                # A window keeps each link whole, in both directions.
                assert await links("get_grades_window", date_from="2026-09-25") == [
                    ("302", ["301"], [])
                ]
                assert await links("get_grades_window", date_to="2026-09-24") == [
                    ("301", [], ["302"])
                ]
                assert not any("/szczegoly/" in path for _, path, _ in wire.calls)


def _behaviour_entry(points, detail_id, day):
    return {
        "points": points,
        "detail_id": detail_id,
        "category": "Fixture behaviour category",
        "day": day,
        "metadata": [
            ["Zakres od", "1"],
            ["Zakres do", "5"],
            ["Data wystawienia", day],
            ["Dodał", "Fixture Teacher"],
            ["Komentarz", "Fixture remark"],
        ],
    }


@pytest.mark.asyncio
async def test_behaviour_points_sit_beside_grades_without_changing_them():
    # #103: the Zachowanie row's points (librus-python-api#138) are reported
    # next to the grade items, uninterpreted, and never become a grade item.
    plus = _behaviour_entry(5, "11", "2026-09-21")
    minus = _behaviour_entry(-3, "12", "2026-09-25")
    async with Wire().serve() as wire:
        with anyio.fail_after(30):
            async with (
                stdio_client(server_process(wire.origin, [("first", "71")])) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()

                async def read(tool, **query):
                    result = await session.call_tool(tool, {"account_alias": "first"} | query)
                    assert not result.is_error, result
                    await assert_matches_published_schema(session, tool, result)
                    return result.structured_content

                for tool in ("get_grades", "get_grades_window"):
                    wire.behaviour_points = False
                    plain = await read(tool, limit=1)
                    assert plain["behaviour_points"] == []
                    wire.behaviour_points = True
                    first = await read(tool, limit=1)
                    # Grade items and their cursor do not depend on the points:
                    # a cursor from the page without them continues this one.
                    for key in ("items", "pagination"):
                        assert first[key] == plain[key]
                    cursor = plain["pagination"]["next_cursor"]
                    last = await read(tool, limit=1, cursor=cursor)
                    assert [item["raw"] for item in first["items"] + last["items"]] == [
                        "4+",
                        "3",
                    ]
                    # Every page carries the points, like get_grades' averages.
                    for page in (first, last):
                        assert page["behaviour_points"][0] == {
                            "semester": 1,
                            "tally": 50,
                            "entries": [plus, minus],
                        }
                whole = await read("get_grades")
                assert whole["behaviour_points"][1] == {
                    "semester": 2,
                    "tally": -7,
                    "entries": [],
                }
                assert all(item["subject"] != "Zachowanie" for item in whole["items"])
                # A window keeps each item's tally with only the entries in it;
                # an item without such entries is left out.
                window = await read("get_grades_window")
                assert [item["tally"] for item in window["behaviour_points"]] == [50]
                dated = await read("get_grades_window", date_from="2026-09-25")
                assert dated["behaviour_points"] == [
                    {"semester": 1, "tally": 50, "entries": [minus]}
                ]
                none = await read("get_grades_window", date_to="2026-09-20")
                assert none["behaviour_points"] == []
                assert not any("zachowanie_szczegoly" in path for _, path, _ in wire.calls)


def _grade(raw, grade_id, day="2026-09-24"):
    href = None if grade_id is None else f"/przegladaj_oceny/szczegoly/{grade_id}"
    return NumericGrade(
        "Fixture", raw, date.fromisoformat(day), 1, None, None, None, None, None, href, ()
    )


def test_each_grade_of_a_chain_links_to_the_grades_before_and_after_it():
    chain = GradeCorrection("Fixture", 1, ("1", "2", "3"))
    items = grade_items(
        (_grade("1", "1"), _grade("2", "2"), _grade("4", "3"), _grade("5", "9")),
        (),
        (),
        (chain,),
    )
    assert [(i.grade_id, i.corrects, i.corrected_by) for i in items] == [
        ("1", (), ("2", "3")),
        ("2", ("1",), ("3",)),
        ("3", ("1", "2"), ()),
        ("9", (), ()),
    ]
    week = grade_items((_grade("4", "3"),), (), (), (chain,), GradeView.WEEK)
    assert [(i.corrects, i.corrected_by) for i in week] == [(None, None)]


def test_a_grade_without_an_id_has_unknown_correction_links():
    # A gateway descriptive grade has no detail link, so no bracket names it.
    unlinked = DescriptiveGrade(
        "Fixture Subject", "Fixture text", date(2026, 9, 24), 1, None, None, ()
    )
    (item,) = grade_items((), (unlinked,), (), corrections=())
    assert (item.grade_id, item.corrects, item.corrected_by) == (None, None, None)


@pytest.mark.asyncio
async def test_point_grades_are_scores_with_their_period_result(tmp_path):
    async with Wire().serve() as wire:
        wire.points = True
        process = server_process(
            wire.origin,
            [("first", "71")],
            features={"notifications": True},
            state_dir=tmp_path / "state",
        )
        with anyio.fail_after(30):
            async with stdio_client(process) as streams, ClientSession(*streams) as session:
                await session.initialize()
                for tool in ("get_grades", "get_grades_window"):
                    grades = await session.call_tool(tool, {"account_alias": "first"})
                    assert not grades.is_error, grades
                    await assert_matches_published_schema(session, tool, grades)
                    items = grades.structured_content["items"]
                    points = [item for item in items if item["record_type"] == "point"]
                    # Same-day items follow their content, not the page order,
                    # which Librus does not keep stable.
                    assert [(item["subject"], item["raw"]) for item in points] == [
                        ("Point Subject", "44"),
                        ("Point Subject", "90"),
                    ]
                    assert points[0]["category"] == "Fixture test (0-100)"
                    assert points[0]["counts_toward_average"] is None
                    assert ["Licz do wyniku", "TAK"] in points[0]["metadata"]
                    assert {item["record_type"] for item in items} == {"numeric", "point"}
                # The period result is a score, kept out of the grade-scale averages.
                assert grades.structured_content.get("point_results") is None
                grades = await session.call_tool("get_grades", {"account_alias": "first"})
                assert grades.structured_content["point_results"][0] == {
                    "subject": "Point Subject",
                    "semester": 1,
                    "value": {"availability": "available", "raw": "67"},
                }
                assert all(
                    average["subject"] == "Example Subject"
                    for average in grades.structured_content["averages"]
                )
                final = await session.call_tool("get_final_grades", {"account_alias": "first"})
                assert not final.is_error, final
                point = final.structured_content["items"][1]
                assert (point["subject"], point["annual"]["raw"]) == ("Point Subject", "-")
                news = await session.call_tool(
                    "get_new_notifications",
                    {"account_alias": "first", "categories": ["grades"]},
                )
                assert not news.is_error, news
                hrefs = {
                    item["value"].get("href") for item in news.structured_content["data"]["items"]
                }
                assert {
                    "/przegladaj_oceny_punktowe/szczegoly/501",
                    "/przegladaj_oceny_punktowe/szczegoly/502",
                } <= hrefs
                assert not any("/szczegoly/" in path for _, path, _ in wire.calls)


@pytest.mark.asyncio
async def test_new_school_and_directory_reads_page_without_losing_native_fields():
    async with Wire().serve() as wire:
        with anyio.fail_after(40):
            async with (
                stdio_client(
                    server_process(wire.origin, [("first", "71"), ("second", "72")])
                ) as streams,
                ClientSession(*streams) as session,
            ):
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
                    assert closed(bad.structured_content) == {"error": {"code": "INVALID_INPUT"}}
                    assert len(wire.calls) == calls
                    last = await session.call_tool(tool, query | {"cursor": cursor})
                    assert not last.is_error, last
                    await assert_matches_published_schema(session, tool, last)
                    assert last.structured_content["pagination"]["next_cursor"] is None
                    pages[tool] = (
                        first.structured_content["items"] + last.structured_content["items"]
                    )
                year, achievement = pages["get_school_year_archive"]
                assert year["record_type"] == "year" and achievement["record_type"] == "achievement"
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
                await assert_matches_published_schema(session, "get_message_unread_counts", counts)
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
                            assert closed(bad.structured_content) == {
                                "error": {"code": "INVALID_INPUT"}
                            }
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
                        assert closed(opened.structured_content) == {
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
                        assert closed(unsupported.structured_content) == {
                            "error": {"code": "UNSUPPORTED_CAPABILITY"}
                        }
                        assert len(wire.calls) == calls


@pytest.mark.asyncio
async def test_justifications_page_in_librus_order_with_the_default_window():
    async with Wire().serve() as wire:
        with anyio.fail_after(40):
            async with (
                stdio_client(
                    server_process(wire.origin, [("first", "71"), ("second", "72")])
                ) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                query = {"account_alias": "first", "limit": 1}
                first = await session.call_tool("get_justifications", query)
                assert not first.is_error, first
                await assert_matches_published_schema(session, "get_justifications", first)
                cursor = first.structured_content["pagination"]["next_cursor"]
                assert first.structured_content["pagination"]["reason"] == "item_limit"
                calls = len(wire.calls)
                bad = await session.call_tool(
                    "get_justifications", query | {"account_alias": "second", "cursor": cursor}
                )
                assert closed(bad.structured_content) == {"error": {"code": "INVALID_INPUT"}}
                assert len(wire.calls) == calls
                last = await session.call_tool("get_justifications", query | {"cursor": cursor})
                assert not last.is_error, last
                await assert_matches_published_schema(session, "get_justifications", last)
                assert last.structured_content["pagination"]["next_cursor"] is None
                for page in (first, last):
                    window = page.structured_content
                    assert (window["date_from"], window["date_to"]) == (
                        "2026-09-24",
                        "2026-10-24",
                    )
                assert first.structured_content["items"] + last.structured_content["items"] == [
                    {
                        "start": "2026-10-01",
                        "end": "2026-10-03",
                        "lessons": [],
                        "absence_count": 4,
                        "content": "Fixture reason\nsecond line",
                        "teachers": ["A. Fixture", "B. Fixture", "C. Fixture"],
                        "sent_at": "2026-10-04T08:15:00",
                        "status": "justified",
                        "decided_by": "D. Fixture",
                        "has_attachment": False,
                    },
                    {
                        "start": "2026-10-07",
                        "end": "2026-10-07",
                        "lessons": [2, 3],
                        "absence_count": 2,
                        "content": "Fixture appointment",
                        "teachers": ["A. Fixture"],
                        "sent_at": "2026-10-07T19:30:05",
                        "status": "sent",
                        "decided_by": None,
                        "has_attachment": False,
                    },
                ]
                wire.justifications_empty = True
                empty = await session.call_tool("get_justifications", {"account_alias": "first"})
                assert not empty.is_error, empty
                await assert_matches_published_schema(session, "get_justifications", empty)
                assert empty.structured_content["items"] == []
                # The list is only read, never filtered by a form POST.
                assert {
                    method for method, path, _ in wire.calls if path == "/eusprawiedliwienia"
                } == {"GET"}


@pytest.mark.asyncio
async def test_a_student_login_gets_unsupported_justifications_without_a_request():
    async with Wire().serve() as wire:
        wire.account_group = 8  # a student login's group
        with anyio.fail_after(30):
            async with (
                stdio_client(server_process(wire.origin, [("first", "71")])) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                result = await session.call_tool("get_justifications", {"account_alias": "first"})
                assert closed(result.structured_content) == {
                    "error": {"code": "UNSUPPORTED_CAPABILITY"}
                }
                assert any(path == "/gateway/api/2.0/Me" for _, path, _ in wire.calls)
                assert not any(path == "/eusprawiedliwienia" for _, path, _ in wire.calls)


def _qualifier():
    path = Path(__file__).resolve().parents[1] / "scripts/qualify_native.py"
    if not path.exists():
        pytest.skip("source checkout only")
    spec = importlib.util.spec_from_file_location("qualify_native", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("group", "empty", "record"),
    [
        (5, False, {"status": "passed", "coverage": "populated", "item_count": 2}),
        (5, True, {"status": "passed", "coverage": "empty", "item_count": 0}),
        (8, False, {"status": "expected_unsupported"}),
        (None, False, {"status": "expected_unsupported"}),
    ],
)
async def test_the_live_qualifier_accepts_any_parent_coverage_and_the_student_refusal(
    group, empty, record
):
    qualifier = _qualifier()
    assert ("get_justifications", {"limit": 5}) in qualifier.cases("v21")
    async with Wire().serve() as wire:
        wire.account_group = group
        wire.justifications_empty = empty
        with anyio.fail_after(30):
            async with (
                stdio_client(server_process(wire.origin, [("first", "71")])) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                records = []
                _, stop = await qualifier.call(
                    session, records, 1, "get_justifications", {"account_alias": "first"}
                )
    assert not stop
    assert records == [{"account_index": 1, "tool": "get_justifications"} | record]
