"""Exercise the published MCP contract through a real stdio subprocess."""

import json
import sys
from pathlib import Path

import anyio
import pytest
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from release_verification.measure_tools import measure_tools

REPOSITORY = Path(__file__).resolve().parents[1]
GRADE_RESPONSE = {
    "numeric": [
        {
            "Math": [
                {
                    "title": "Math",
                    "grade": "5",
                    "counts": True,
                    "date": "2026-09-01",
                    "href": "/grades/1",
                    "desc": "Classwork",
                    "semester": 1,
                    "category": "classwork",
                    "teacher": "Teacher",
                    "weight": 1,
                }
            ]
        }
    ],
    "gpa": {"Math": [{"semester": 1, "gpa": 5.0, "subject": "Math"}]},
    "descriptive": [{}],
}


def _server(child_script: str, *, notifications: bool = False) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-c", child_script],
        cwd=REPOSITORY,
        env={
            "LIBRUS_ACCOUNTS": json.dumps(
                [{"alias": "synthetic", "username": "synthetic", "password": "synthetic"}]
            ),
            "LIBRUS_FEATURES": json.dumps({"notifications": notifications, "attachments": False}),
        },
    )


@pytest.mark.asyncio
async def test_tool_catalog_fits_context_budget():
    default = await measure_tools(False)
    all_features = await measure_tools(True)

    assert default["with_output_schema"] == default["tools"]
    # send_message keeps its heterogeneous preview/delivery result until its
    # separate write-contract review; all other opt-in tools advertise schemas.
    assert all_features["with_output_schema"] == all_features["tools"] - 1
    assert default["bytes"] <= 48 * 1024
    assert all_features["bytes"] <= 64 * 1024


@pytest.mark.asyncio
async def test_stdio_lists_typed_tools_and_preserves_grade_content():
    # Replace only the Librus network boundary; CLI startup, stdio transport,
    # tool registration, result validation and JSON-RPC all remain real.
    child_script = (
        "from unittest.mock import AsyncMock, patch\n"
        "from src.cli import main\n"
        "from src.librus_client import LibrusManager\n"
        f"grades = {GRADE_RESPONSE!r}\n"
        "with patch.object(LibrusManager, 'fetch_grades', AsyncMock(return_value=grades)):\n"
        "    main([])\n"
    )
    with anyio.fail_after(30):
        async with stdio_client(_server(child_script)) as streams:
            async with ClientSession(*streams) as session:
                initialization = await session.initialize()
                assert initialization.server_info.name == "librus-mcp"

                listing = await session.list_tools()
                tools = {tool.name: tool for tool in listing.tools}
                assert "get_grades" in tools
                assert "send_message" not in tools
                assert set(tools["get_grades"].output_schema["required"]) == {
                    "numeric",
                    "gpa",
                    "descriptive",
                }

                result = await session.call_tool("get_grades", {"student_alias": "synthetic"})
                assert result.is_error is not True
                assert json.loads(result.content[0].text) == GRADE_RESPONSE
                assert result.structured_content == GRADE_RESPONSE

                rejected = await session.call_tool("get_grades", {"student_alias": ""})
                assert rejected.is_error is True


@pytest.mark.asyncio
async def test_stdio_message_modes_preserve_null_and_absent_fields():
    message = {
        "author": "Teacher",
        "title": "School trip",
        "date": "2026-09-01",
        "href": "123",
        "unread": False,
        "has_attachment": False,
    }
    received = {
        "messages": [message],
        "folder": "received",
        "page": 0,
        "max_page": 0,
        "truncated": False,
    }
    sent = {**received, "folder": "sent", "max_page": None}
    all_pages = {
        "messages": [message],
        "folder": "received",
        "pages_fetched": 1,
        "truncated": False,
    }
    child_script = (
        "from unittest.mock import AsyncMock, patch\n"
        "from src.cli import main\n"
        "from src.librus_client import LibrusManager\n"
        f"received, sent, all_pages = {received!r}, {sent!r}, {all_pages!r}\n"
        "with (\n"
        "    patch.object(LibrusManager, 'fetch_messages', AsyncMock(side_effect=[received, sent])),\n"
        "    patch.object(LibrusManager, 'fetch_all_messages', AsyncMock(return_value=all_pages)),\n"
        "):\n"
        "    main([])\n"
    )
    with anyio.fail_after(30):
        async with stdio_client(_server(child_script)) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                for arguments, expected in (
                    ({"student_alias": "synthetic"}, received),
                    ({"student_alias": "synthetic", "folder": "sent"}, sent),
                    ({"student_alias": "synthetic", "all_pages": True}, all_pages),
                ):
                    result = await session.call_tool("get_messages", arguments)
                    assert result.is_error is not True
                    assert json.loads(result.content[0].text) == expected
                    assert result.structured_content == expected


@pytest.mark.asyncio
async def test_stdio_schedule_and_timetable_keep_json_shapes():
    event = {
        "title": "Test",
        "subject": "Math",
        "data": {"Opis": "Algebra"},
        "day": "1",
        "number": 1,
        "hour": "unknown",
        "href": "szczegoly/123",
    }
    period = {
        "subject": "Math",
        "teacher_and_classroom": "Teacher 101",
        "date": "2026-09-21",
        "date_from": "08:00",
        "date_to": "08:45",
        "weekday": "Monday",
        "info": {},
        "number": 1,
        "next_recess_from": None,
        "next_recess_to": None,
    }
    child_script = (
        "from unittest.mock import AsyncMock, patch\n"
        "from src.cli import main\n"
        "from src.librus_client import LibrusManager\n"
        f"event, period = {event!r}, {period!r}\n"
        "with (\n"
        "    patch.object(LibrusManager, 'fetch_schedule', AsyncMock(return_value={1: [event]})),\n"
        "    patch.object(LibrusManager, 'fetch_timetable', AsyncMock(return_value=[[period]])),\n"
        "):\n"
        "    main([])\n"
    )
    with anyio.fail_after(30):
        async with stdio_client(_server(child_script)) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                schedule = await session.call_tool(
                    "get_schedule", {"student_alias": "synthetic", "year": "2026", "month": "9"}
                )
                assert schedule.is_error is not True
                assert json.loads(schedule.content[0].text) == {"1": [event]}
                assert schedule.structured_content == {"1": [event]}

                timetable = await session.call_tool(
                    "get_timetable", {"student_alias": "synthetic", "monday": "2026-09-21"}
                )
                assert timetable.is_error is not True
                assert json.loads(timetable.content[0].text) == period
                assert timetable.structured_content == {"result": [[period]]}


@pytest.mark.asyncio
async def test_stdio_message_and_frequency_require_known_fields():
    detail = {
        "author": "Teacher",
        "title": "School trip",
        "date": "2026-09-01",
        "content": "Details",
    }
    frequency = {"first_semester": 0.8, "second_semester": 0.9, "overall": 0.85}
    child_script = (
        "from unittest.mock import AsyncMock, patch\n"
        "from src.cli import main\n"
        "from src.librus_client import LibrusManager\n"
        f"detail, frequency = {detail!r}, {frequency!r}\n"
        "with (\n"
        "    patch.object(LibrusManager, 'fetch_message_content', AsyncMock("
        "side_effect=[detail, {'author': 'Teacher'}])),\n"
        "    patch.object(LibrusManager, 'fetch_attendance_frequency', AsyncMock("
        "side_effect=[frequency, {'first_semester': 0.8}])),\n"
        "):\n"
        "    main([])\n"
    )
    with anyio.fail_after(30):
        async with stdio_client(_server(child_script)) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                for tool_name, arguments, expected in (
                    (
                        "get_message_content",
                        {"student_alias": "synthetic", "message_id": "1"},
                        detail,
                    ),
                    ("get_attendance_frequency", {"student_alias": "synthetic"}, frequency),
                ):
                    result = await session.call_tool(tool_name, arguments)
                    assert result.is_error is not True
                    assert json.loads(result.content[0].text) == expected
                    assert result.structured_content == expected
                    invalid = await session.call_tool(tool_name, arguments)
                    assert invalid.is_error is True


@pytest.mark.asyncio
async def test_stdio_optional_notification_shape_without_consuming_live_events():
    child_script = (
        "from unittest.mock import AsyncMock, patch\n"
        "from librus_apix.notifications import NotificationData\n"
        "from src.cli import main\n"
        "from src.librus_client import LibrusManager\n"
        "new = NotificationData([], [], [], [], [], [])\n"
        "with patch.object(LibrusManager, 'fetch_new_notifications', "
        "AsyncMock(return_value={'first_run': True, 'new': new})):\n"
        "    main([])\n"
    )
    expected = {
        "first_run": True,
        "new": {
            "grades": [],
            "attendance": [],
            "messages": [],
            "announcements": [],
            "schedule": [],
            "homework": [],
        },
    }
    with anyio.fail_after(30):
        async with stdio_client(_server(child_script, notifications=True)) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert tools["get_new_notifications"].annotations.read_only_hint is False

                result = await session.call_tool(
                    "get_new_notifications", {"student_alias": "synthetic"}
                )
                assert result.is_error is not True
                assert json.loads(result.content[0].text) == expected
                assert result.structured_content == expected
