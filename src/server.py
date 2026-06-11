from typing import Any
import dataclasses

from mcp.server.fastmcp import FastMCP
from src.librus_client import LibrusManager

mcp = FastMCP("librus-mcp")


def to_dict(obj: Any) -> Any:
    """Convert dataclasses to dicts recursively for JSON serialization."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [to_dict(i) for i in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    assert isinstance(obj, (str, int, float, bool, type(None))), (
        f"to_dict received non-serializable type: {type(obj).__name__}"
    )
    return obj


@mcp.tool()
async def list_students() -> list[str]:
    """
    Lists the aliases of configured students/accounts.
    """
    return LibrusManager.list_accounts()


@mcp.tool()
async def get_grades(student_alias: str) -> Any:
    """
    Fetches grades for the specified student. Returns numeric grades, GPA, and descriptive grades.
    Args:
        student_alias: The alias of the student (e.g., 'daughter', 'son').
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    grades = await LibrusManager.fetch_grades(student_alias)
    return to_dict(grades)


@mcp.tool()
async def get_messages(student_alias: str, page: int = 0, folder: str = "received") -> Any:
    """
    Fetches one page of messages for the specified student.
    Args:
        student_alias: The alias of the student.
        page: 0-based page number; page 0 holds the newest messages. The response
            includes max_page (last valid index) for the received folder. For the
            sent folder max_page is null because Librus exposes no page counter
            there — null does NOT mean the current page is the last one. Pages
            hold 50 messages; a page with fewer than 50 is the last one (Librus
            clamps out-of-range pages to the last page instead of returning empty).
        folder: Message folder, 'received' or 'sent'. Defaults to 'received'.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    messages = await LibrusManager.fetch_messages(student_alias, page, folder)
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
async def get_subject_frequency(
    student_alias: str,
    start: str | None = None,
    end: str | None = None,
) -> Any:
    """
    Fetches per-subject attendance frequency (percentage) for the specified student.
    Optionally filter by date range.
    Args:
        student_alias: The alias of the student.
        start: Optional start date in YYYY-MM-DD format.
        end: Optional end date in YYYY-MM-DD format.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    frequency = await LibrusManager.fetch_subject_frequency(student_alias, start, end)
    return to_dict(frequency)


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
async def get_homework_detail(student_alias: str, detail_url: str) -> Any:
    """
    Fetches full details of a specific homework assignment.
    Args:
        student_alias: The alias of the student.
        detail_url: The detail URL from the homework list (the 'href' field).
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    assert detail_url, "detail_url must not be empty"
    detail = await LibrusManager.fetch_homework_detail(student_alias, detail_url)
    return to_dict(detail)


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


@mcp.tool()
async def get_completed_lessons(student_alias: str, date_from: str, date_to: str) -> Any:
    """
    Fetches completed lessons (subject, teacher, topic) for a date range.
    Args:
        student_alias: The alias of the student.
        date_from: Start date in YYYY-MM-DD format.
        date_to: End date in YYYY-MM-DD format.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    assert date_from, "date_from must not be empty"
    assert date_to, "date_to must not be empty"
    lessons = await LibrusManager.fetch_completed_lessons(student_alias, date_from, date_to)
    return to_dict(lessons)


@mcp.tool()
async def get_student_information(student_alias: str) -> Any:
    """
    Fetches student profile information (name, class, tutor, school, lucky number).
    Args:
        student_alias: The alias of the student.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    info = await LibrusManager.fetch_student_information(student_alias)
    return to_dict(info)


@mcp.tool()
async def get_final_grades(student_alias: str) -> Any:
    """
    Fetches end-of-year grade summary per subject: midterm grade, predicted
    annual grade (przewidywana roczna), and the annual grade once issued.
    A '-' value means the grade has not been issued yet.
    Args:
        student_alias: The alias of the student.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    grades = await LibrusManager.fetch_final_grades(student_alias)
    return to_dict(grades)


@mcp.tool()
async def get_recent_schedule_events(student_alias: str) -> Any:
    """
    Fetches schedule events added since the last Librus login (new tests, trips, meetings).
    Args:
        student_alias: The alias of the student.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    events = await LibrusManager.fetch_recent_schedule_events(student_alias)
    return to_dict(events)


# --- Optional tools, registered by register_optional_tools() based on config features ---


async def get_new_notifications(student_alias: str) -> Any:
    """
    Returns what is new since the previous call: grades, attendance, messages,
    announcements, schedule events, and homework. Seen-state is persisted per
    student, so each item is reported only once. On the first call for a student
    it returns the baseline (items since last Librus login) with first_run=true.
    Args:
        student_alias: The alias of the student.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    result = await LibrusManager.fetch_new_notifications(student_alias)
    return to_dict(result)


async def get_message_attachments(student_alias: str, message_id: str) -> Any:
    """
    Lists attachments (filename, message_id, file_id) of a specific message.
    Args:
        student_alias: The alias of the student.
        message_id: The ID of the message (from the 'href' field in message list).
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    assert message_id, "message_id must not be empty"
    attachments = await LibrusManager.fetch_message_attachments(student_alias, message_id)
    return to_dict(attachments)


async def download_attachment(student_alias: str, message_id: str, file_id: str) -> Any:
    """
    Downloads a message attachment to the configured download directory
    (LIBRUS_DOWNLOAD_DIR env, 'download_dir' in secrets.json, or ~/.librus-mcp/downloads).
    Returns the saved path, filename, size, and content type.
    Args:
        student_alias: The alias of the student.
        message_id: The ID of the message.
        file_id: The ID of the file (from get_message_attachments).
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    assert message_id, "message_id must not be empty"
    assert file_id, "file_id must not be empty"
    info = await LibrusManager.download_message_attachment(student_alias, message_id, file_id)
    return to_dict(info)


async def get_behaviour_notes(student_alias: str) -> Any:
    """
    Fetches behaviour notes (uwagi) for the specified student: date, teacher,
    category, and content. Returns an empty list when there are no notes.
    Args:
        student_alias: The alias of the student.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    notes = await LibrusManager.fetch_behaviour_notes(student_alias)
    return to_dict(notes)


async def get_recipient_groups(student_alias: str) -> Any:
    """
    Lists recipient group identifiers available for sending messages.
    Args:
        student_alias: The alias of the student.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    groups = await LibrusManager.fetch_recipient_groups(student_alias)
    return to_dict(groups)


async def get_recipients(student_alias: str, group: str) -> Any:
    """
    Lists recipients (name -> recipient ID) in a recipient group.
    Args:
        student_alias: The alias of the student.
        group: A group identifier from get_recipient_groups.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    assert group, "group must not be empty"
    recipients = await LibrusManager.fetch_recipients(student_alias, group)
    return to_dict(recipients)


async def send_message(
    student_alias: str, title: str, content: str, recipient_ids: list[str]
) -> Any:
    """
    Sends a message to school staff via the Librus messaging system.
    WRITE ACTION: this delivers a real message to teachers. Disabled by default;
    enable with features.send_message in the configuration.
    Args:
        student_alias: The alias of the student.
        title: Message subject.
        content: Message body.
        recipient_ids: Recipient IDs from get_recipients.
    """
    assert student_alias, "student_alias must not be empty"
    assert isinstance(student_alias, str), "student_alias must be a string"
    assert title, "title must not be empty"
    assert content, "content must not be empty"
    assert isinstance(recipient_ids, list), "recipient_ids must be a list"
    assert len(recipient_ids) > 0, "recipient_ids must not be empty"
    result = await LibrusManager.send_message_to(student_alias, title, content, recipient_ids)
    return to_dict(result)


_FEATURE_TOOLS: dict[str, list[Any]] = {
    "notifications": [get_new_notifications],
    "attachments": [get_message_attachments, download_attachment],
    "behaviour_notes": [get_behaviour_notes],
    "send_message": [get_recipient_groups, get_recipients, send_message],
}
_registered_optional_tools: set[str] = set()


def register_optional_tools() -> list[str]:
    """Register feature-gated tools per config. Idempotent; returns newly added names."""
    features = LibrusManager._get_config().features
    registered: list[str] = []
    for feature_name, tools in _FEATURE_TOOLS.items():
        enabled = getattr(features, feature_name)
        assert isinstance(enabled, bool), f"feature '{feature_name}' must be a bool"
        if not enabled:
            continue
        for tool in tools:
            if tool.__name__ in _registered_optional_tools:
                continue
            mcp.add_tool(tool)
            _registered_optional_tools.add(tool.__name__)
            registered.append(tool.__name__)
    return registered


def main():
    register_optional_tools()
    mcp.run()


if __name__ == "__main__":
    main()
