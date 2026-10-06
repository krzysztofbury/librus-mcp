"""Ordinary family projections through real native contracts and MCP serialization."""

import anyio
import pytest
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client

from tests_native.test_native_stdio import server_process
from tests_native.wire import Wire


@pytest.mark.asyncio
async def test_remaining_academic_families_preserve_native_values_and_bound_references():
    async with Wire().serve() as wire:
        with anyio.fail_after(45):
            async with (
                stdio_client(
                    server_process(wire.origin, [("account", "71"), ("other", "72")])
                ) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                base = {"account_alias": "account"}

                async def call(name, arguments=None):
                    result = await session.call_tool(name, base | (arguments or {}))
                    assert not result.is_error, result
                    assert result.structured_content["observation"]["account"] == "account"
                    return result.structured_content

                detail = await call("get_attendance_detail", {"attendance_id": "81"})
                assert detail["data"]["normalized_fields"][0]["value"] == "Fixture detail"
                window = await call(
                    "get_attendance_window", {"date_from": "2026-09-24", "date_to": "2026-09-24"}
                )
                assert window["items"][0]["symbol"] == "nb"
                frequency = await call("get_attendance_frequency")
                assert frequency["data"]["overall"] == {
                    "attended_count": 2,
                    "total_count": 4,
                    "ratio": None,
                    "excluded_count": 0,
                    "unknown_count": 1,
                    "policy": "overall",
                }
                subjects = await call(
                    "get_subject_frequency", {"date_from": "2026-09-24", "date_to": "2026-09-24"}
                )
                assert subjects["items"][0]["subject"] == "Fixture Subject"
                assert subjects["items"][0]["frequency"] == {
                    "attended_count": 1,
                    "total_count": 2,
                    "excluded_count": 1,
                    "unknown_count": 1,
                    "ratio": None,
                    "policy": "subject",
                }
                timetable = await call("get_timetable", {"monday": "2026-09-21"})
                assert [item["day"] for item in timetable["items"]] == [
                    f"2026-09-{day}" for day in range(21, 28)
                ]
                assert timetable["items"][0]["periods"][0]["interval"] == {
                    "starts_at": "08:00:00",
                    "ends_at": "08:45:00",
                }
                notices = await call("get_announcements")
                assert notices["items"][0]["content"] == "Inert notice text"
                agenda = await call("get_agenda", {"year": 2026, "month": 9})
                homework = await call(
                    "get_homework", {"date_from": "2026-09-24", "date_to": "2026-09-25"}
                )
                assert agenda["items"][0]["day"] == "2026-09-24"
                assert homework["items"][0]["due_on"] == "2026-09-25"
                for name, field, source in (
                    ("get_agenda_detail", "event_ref", agenda),
                    ("get_homework_detail", "homework_ref", homework),
                ):
                    reference = source["items"][0]["reference"]
                    calls = len(wire.calls)
                    invalid = await session.call_tool(
                        name, {"account_alias": "other", field: reference}
                    )
                    assert invalid.is_error and len(wire.calls) == calls
                    assert (await call(name, {field: reference}))["data"]["normalized_fields"][0][
                        "value"
                    ] == "Fixture detail"
                query = {"date_from": "2026-09-24", "date_to": "2026-09-24", "limit": 1}
                lessons = await call("get_completed_lessons", query)
                cursor = lessons["pagination"]["next_cursor"]
                assert lessons["items"][0]["topic"] == "Fixture topic 1"
                calls = len(wire.calls)
                invalid = await session.call_tool(
                    "get_completed_lessons",
                    base | query | {"cursor": cursor, "account_alias": "other"},
                )
                assert invalid.is_error and len(wire.calls) == calls
                continued = await call("get_completed_lessons", query | {"cursor": cursor})
                assert continued["items"][0]["topic"] == "Fixture topic 2"
                assert continued["pagination"]["next_cursor"] is None
                assert not any(
                    "dodane_od_ostatniego" in path or "oznacz" in path for _, path, _ in wire.calls
                )
