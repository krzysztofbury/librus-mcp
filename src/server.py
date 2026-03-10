import sys
import os

# Allow imports from src when running the script directly.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from src.librus_client import LibrusManager
from src.patches import apply_patches
from typing import List, Any
import dataclasses

apply_patches()

mcp = FastMCP("librus-mcp")


def to_dict(obj: Any) -> Any:
    """Convert dataclasses to dicts recursively for JSON serialization."""
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [to_dict(i) for i in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


@mcp.tool()
async def list_students() -> List[str]:
    """
    Lists the aliases of configured students/accounts.
    """
    return LibrusManager.list_accounts()


@mcp.tool()
async def get_grades(student_alias: str) -> Any:
    """
    Fetches grades for the specified student.
    Args:
        student_alias: The alias of the student (e.g., 'daughter', 'son').
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    grades = await LibrusManager.fetch_grades(student_alias)
    return to_dict(grades)


@mcp.tool()
async def get_messages(student_alias: str) -> Any:
    """
    Fetches received messages for the specified student.
    Args:
        student_alias: The alias of the student.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    messages = await LibrusManager.fetch_messages(student_alias)
    return to_dict(messages)


@mcp.tool()
async def get_message_content(student_alias: str, message_id: str) -> str:
    """
    Fetches the content of a specific message.
    Args:
        student_alias: The alias of the student.
        message_id: The ID of the message (from the 'href' field in message list).
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    assert message_id, "message_id must not be empty"
    content = await LibrusManager.fetch_message_content(student_alias, message_id)
    return content


@mcp.tool()
async def get_attendance(student_alias: str) -> Any:
    """
    Fetches attendance records for the specified student.
    Args:
        student_alias: The alias of the student.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    attendance = await LibrusManager.fetch_attendance(student_alias)
    return to_dict(attendance)


@mcp.tool()
async def get_homework(student_alias: str) -> Any:
    """
    Fetches homework for the next 2 weeks for the specified student.
    Args:
        student_alias: The alias of the student.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    homework = await LibrusManager.fetch_homework(student_alias)
    return to_dict(homework)


@mcp.tool()
async def get_schedule(student_alias: str, year: str, month: str) -> Any:
    """
    Fetches the schedule (calendar events, exams) for a specific month and year.
    Args:
        student_alias: The alias of the student.
        year: The year (e.g., '2026').
        month: The month (e.g., '1' or '01').
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    assert year.isdigit(), "Year must be a number"
    assert month.isdigit(), "Month must be a number"
    schedule = await LibrusManager.fetch_schedule(student_alias, month, year)
    return to_dict(schedule)


@mcp.tool()
async def get_timetable(student_alias: str) -> Any:
    """
    Fetches the timetable (lessons) for the current week for the specified student.
    Args:
        student_alias: The alias of the student.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    timetable = await LibrusManager.fetch_timetable(student_alias)
    return to_dict(timetable)


@mcp.tool()
async def get_announcements(student_alias: str) -> Any:
    """
    Fetches school announcements for the specified student.
    Args:
        student_alias: The alias of the student.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    announcements = await LibrusManager.fetch_announcements(student_alias)
    return to_dict(announcements)


if __name__ == "__main__":
    mcp.run()
