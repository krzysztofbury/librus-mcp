import dataclasses
import hashlib
import json
import secrets
import time
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from src import __version__
from src.librus_client import LibrusManager

# Passing version explicitly: an unversioned server advertises an empty version
# in the initialize handshake, so hosts would show no version for this server.
mcp = MCPServer("librus-mcp", version=__version__)

# Every tool talks to the external Librus service, hence open_world_hint on all.
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
# Mutates local state only (seen-notification IDs / downloaded files), nothing
# at the school; not idempotent because repeated calls yield different results.
LOCAL_STATE_WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)
SEND_MESSAGE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True
)

StudentAlias = Annotated[str, Field(min_length=1, description="Alias of the student account")]
# Message and file identifiers are bare numeric path segments in Synergia.
NumericId = Annotated[str, Field(pattern=r"^\d+$")]
IsoDate = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
SortBy = Literal["all", "week", "last_login"]


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


@mcp.tool(annotations=READ_ONLY)
async def list_students() -> list[str]:
    """
    Lists the aliases of configured students/accounts.
    """
    return LibrusManager.list_accounts()


@mcp.tool(annotations=READ_ONLY)
async def get_grades(student_alias: StudentAlias, sort_by: SortBy = "all") -> Any:
    """
    Fetches grades for the specified student. Returns numeric grades, GPA, and descriptive grades.
    Args:
        student_alias: The alias of the student (e.g., 'daughter', 'son').
        sort_by: 'all' (default), 'week' (current week only), or 'last_login'
            (grades added since the last Librus login).
    """
    grades = await LibrusManager.fetch_grades(student_alias, sort_by)
    return to_dict(grades)


@mcp.tool(annotations=READ_ONLY)
async def get_messages(
    student_alias: StudentAlias,
    page: Annotated[int, Field(ge=0, le=1000)] = 0,
    folder: Literal["received", "sent"] = "received",
    all_pages: bool = False,
) -> Any:
    """
    Fetches one page of messages for the specified student (or the whole folder).
    Args:
        student_alias: The alias of the student.
        page: 0-based page number; page 0 holds the newest messages. The response
            includes max_page (last valid index) for the received folder. For the
            sent folder max_page is null because Librus exposes no page counter
            there — null does NOT mean the current page is the last one. Pages
            hold 50 messages; a page with fewer than 50 is the last one (Librus
            clamps out-of-range pages to the last page instead of returning empty).
        folder: Message folder, 'received' or 'sent'. Defaults to 'received'.
        all_pages: When true, ignores `page` and fetches the whole folder
            (newest first), bounded at 2000 messages; the response then has
            pages_fetched and truncated instead of page/max_page.
    """
    if all_pages:
        messages = await LibrusManager.fetch_all_messages(student_alias, folder)
    else:
        messages = await LibrusManager.fetch_messages(student_alias, page, folder)
    return to_dict(messages)


@mcp.tool(annotations=READ_ONLY)
async def get_message_content(student_alias: StudentAlias, message_id: NumericId) -> dict[str, str]:
    """
    Fetches a specific message: author, title, date, and content.
    Args:
        student_alias: The alias of the student.
        message_id: The numeric ID of the message (from the 'href' field in message list).
    """
    return await LibrusManager.fetch_message_content(student_alias, message_id)


@mcp.tool(annotations=READ_ONLY)
async def get_attendance(student_alias: StudentAlias, sort_by: SortBy = "all") -> Any:
    """
    Fetches attendance records for the specified student, grouped by semester.
    Args:
        student_alias: The alias of the student.
        sort_by: 'all' (default), 'week' (current week only), or 'last_login'
            (records added since the last Librus login).
    """
    attendance = await LibrusManager.fetch_attendance(student_alias, sort_by)
    return to_dict(attendance)


@mcp.tool(annotations=READ_ONLY)
async def get_attendance_detail(student_alias: StudentAlias, detail_url: NumericId) -> Any:
    """
    Fetches details of one attendance entry (lesson, teacher, trip type, etc.).
    Args:
        student_alias: The alias of the student.
        detail_url: The numeric 'href' identifier from an attendance record.
    """
    detail = await LibrusManager.fetch_attendance_detail(student_alias, detail_url)
    return to_dict(detail)


@mcp.tool(annotations=READ_ONLY)
async def get_attendance_frequency(student_alias: StudentAlias) -> dict[str, float]:
    """
    Fetches attendance frequency ratios (0..1) for the first semester, second
    semester, and overall school year.
    Args:
        student_alias: The alias of the student.
    """
    return await LibrusManager.fetch_attendance_frequency(student_alias)


@mcp.tool(annotations=READ_ONLY)
async def get_subject_frequency(
    student_alias: StudentAlias,
    start: IsoDate | None = None,
    end: IsoDate | None = None,
) -> Any:
    """
    Fetches per-subject attendance frequency (percentage) for the specified student.
    Optionally filter by date range.
    Args:
        student_alias: The alias of the student.
        start: Optional start date in YYYY-MM-DD format.
        end: Optional end date in YYYY-MM-DD format.
    """
    frequency = await LibrusManager.fetch_subject_frequency(student_alias, start, end)
    return to_dict(frequency)


@mcp.tool(annotations=READ_ONLY)
async def get_homework(
    student_alias: StudentAlias,
    date_from: IsoDate | None = None,
    date_to: IsoDate | None = None,
) -> Any:
    """
    Fetches homework for a date range; defaults to the next 2 weeks.
    Args:
        student_alias: The alias of the student.
        date_from: Optional start date in YYYY-MM-DD format (provide both dates or neither).
        date_to: Optional end date in YYYY-MM-DD format, at most 370 days after date_from.
    """
    homework = await LibrusManager.fetch_homework(student_alias, date_from, date_to)
    return to_dict(homework)


@mcp.tool(annotations=READ_ONLY)
async def get_homework_detail(student_alias: StudentAlias, detail_url: NumericId) -> Any:
    """
    Fetches full details of a specific homework assignment.
    Args:
        student_alias: The alias of the student.
        detail_url: The numeric detail identifier from the homework list.
    """
    detail = await LibrusManager.fetch_homework_detail(student_alias, detail_url)
    return to_dict(detail)


@mcp.tool(annotations=READ_ONLY)
async def get_schedule(
    student_alias: StudentAlias,
    year: Annotated[str, Field(pattern=r"^\d{4}$")],
    month: Annotated[str, Field(pattern=r"^\d{1,2}$")],
) -> Any:
    """
    Fetches the schedule (calendar events, exams) for a specific month and year.
    Args:
        student_alias: The alias of the student.
        year: The year (e.g., '2026').
        month: The month (e.g., '1' or '01').
    """
    schedule = await LibrusManager.fetch_schedule(student_alias, month, year)
    return to_dict(schedule)


@mcp.tool(annotations=READ_ONLY)
async def get_schedule_detail(student_alias: StudentAlias, href: str) -> Any:
    """
    Fetches details of one schedule event (test scope, room, teacher, etc.).
    Args:
        student_alias: The alias of the student.
        href: The 'href' field of an event from get_schedule or
            get_recent_schedule_events, e.g. 'szczegoly/12345'.
    """
    detail = await LibrusManager.fetch_schedule_detail(student_alias, href)
    return to_dict(detail)


@mcp.tool(annotations=READ_ONLY)
async def get_timetable(student_alias: StudentAlias, monday: IsoDate | None = None) -> Any:
    """
    Fetches the timetable (lessons) for one week.
    Args:
        student_alias: The alias of the student.
        monday: Optional week start in YYYY-MM-DD format; must be a Monday.
            Defaults to the current week.
    """
    timetable = await LibrusManager.fetch_timetable(student_alias, monday)
    return to_dict(timetable)


@mcp.tool(annotations=READ_ONLY)
async def get_announcements(student_alias: StudentAlias) -> Any:
    """
    Fetches school announcements for the specified student.
    Args:
        student_alias: The alias of the student.
    """
    announcements = await LibrusManager.fetch_announcements(student_alias)
    return to_dict(announcements)


@mcp.tool(annotations=READ_ONLY)
async def get_completed_lessons(
    student_alias: StudentAlias, date_from: IsoDate, date_to: IsoDate
) -> Any:
    """
    Fetches completed lessons (subject, teacher, topic) for a date range.
    Args:
        student_alias: The alias of the student.
        date_from: Start date in YYYY-MM-DD format.
        date_to: End date in YYYY-MM-DD format.
    """
    lessons = await LibrusManager.fetch_completed_lessons(student_alias, date_from, date_to)
    return to_dict(lessons)


@mcp.tool(annotations=READ_ONLY)
async def get_student_information(student_alias: StudentAlias) -> Any:
    """
    Fetches student profile information (name, class, tutor, school, lucky number).
    Args:
        student_alias: The alias of the student.
    """
    info = await LibrusManager.fetch_student_information(student_alias)
    return to_dict(info)


@mcp.tool(annotations=READ_ONLY)
async def get_final_grades(student_alias: StudentAlias) -> Any:
    """
    Fetches end-of-year grade summary per subject: midterm grade, predicted
    annual grade (przewidywana roczna), and the annual grade once issued.
    A '-' value means the grade has not been issued yet.
    Args:
        student_alias: The alias of the student.
    """
    grades = await LibrusManager.fetch_final_grades(student_alias)
    return to_dict(grades)


@mcp.tool(annotations=READ_ONLY)
async def get_recent_schedule_events(student_alias: StudentAlias) -> Any:
    """
    Fetches schedule events added since the last Librus login (new tests, trips, meetings).
    Args:
        student_alias: The alias of the student.
    """
    events = await LibrusManager.fetch_recent_schedule_events(student_alias)
    return to_dict(events)


# --- Optional tools, registered by register_optional_tools() based on config features ---


async def get_new_notifications(student_alias: StudentAlias) -> Any:
    """
    Returns what is new since the previous call: grades, attendance, messages,
    announcements, schedule events, and homework. Seen-state is persisted per
    student, so each item is reported only once. On the first call for a student
    it returns the baseline (items since last Librus login) with first_run=true.
    Args:
        student_alias: The alias of the student.
    """
    result = await LibrusManager.fetch_new_notifications(student_alias)
    return to_dict(result)


async def get_message_attachments(student_alias: StudentAlias, message_id: NumericId) -> Any:
    """
    Lists attachments (filename, message_id, file_id) of a specific message.
    Args:
        student_alias: The alias of the student.
        message_id: The numeric ID of the message (from the 'href' field in message list).
    """
    attachments = await LibrusManager.fetch_message_attachments(student_alias, message_id)
    return to_dict(attachments)


async def download_attachment(
    student_alias: StudentAlias, message_id: NumericId, file_id: NumericId
) -> Any:
    """
    Downloads a message attachment to the configured download directory
    (LIBRUS_DOWNLOAD_DIR env, 'download_dir' in secrets.json, or ~/.librus-mcp/downloads).
    Never overwrites: a name collision gets a ' (n)' suffix. Returns the saved
    path, filename, size, and content type.
    Args:
        student_alias: The alias of the student.
        message_id: The numeric ID of the message.
        file_id: The numeric ID of the file (from get_message_attachments).
    """
    info = await LibrusManager.download_message_attachment(student_alias, message_id, file_id)
    return to_dict(info)


async def get_behaviour_notes(student_alias: StudentAlias) -> Any:
    """
    Fetches behaviour notes (uwagi) for the specified student: date, teacher,
    category, and content. Returns an empty list when there are no notes.
    Args:
        student_alias: The alias of the student.
    """
    notes = await LibrusManager.fetch_behaviour_notes(student_alias)
    return to_dict(notes)


async def get_recipient_groups(student_alias: StudentAlias) -> Any:
    """
    Lists recipient group identifiers available for sending messages.
    Args:
        student_alias: The alias of the student.
    """
    groups = await LibrusManager.fetch_recipient_groups(student_alias)
    return to_dict(groups)


async def get_recipients(student_alias: StudentAlias, group: str) -> Any:
    """
    Lists recipients (name -> recipient ID) in a recipient group.
    Args:
        student_alias: The alias of the student.
        group: A group identifier from get_recipient_groups.
    """
    recipients = await LibrusManager.fetch_recipients(student_alias, group)
    return to_dict(recipients)


SEND_CONFIRMATION_TTL_SECONDS = 300.0
MAX_PENDING_CONFIRMATIONS = 32
# token -> (payload digest, monotonic deadline). In-memory: a server restart
# invalidates pending confirmations, which fails safe (no send happens).
_pending_confirmations: dict[str, tuple[str, float]] = {}


def _confirmation_digest(
    student_alias: str, title: str, content: str, recipient_ids: list[str]
) -> str:
    canonical = json.dumps(
        [student_alias, title, content, sorted(recipient_ids)], ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _issue_confirmation(digest: str) -> str:
    now = time.monotonic()
    expired = [token for token, (_, deadline) in _pending_confirmations.items() if deadline < now]
    for token in expired:
        del _pending_confirmations[token]
    if len(_pending_confirmations) >= MAX_PENDING_CONFIRMATIONS:
        raise ValueError("too many pending send confirmations; retry in a few minutes")
    token = secrets.token_urlsafe(16)
    _pending_confirmations[token] = (digest, now + SEND_CONFIRMATION_TTL_SECONDS)
    return token


def _redeem_confirmation(token: str, digest: str) -> None:
    """Tokens are single-use and expire: pop unconditionally so a failed send
    cannot be blindly retried with the same token."""
    entry = _pending_confirmations.pop(token, None)
    if entry is None:
        raise ValueError(
            "unknown or already-used confirm_token; call send_message without "
            "confirm_token to get a new one"
        )
    stored_digest, deadline = entry
    if time.monotonic() > deadline:
        raise ValueError("confirm_token expired; call send_message without confirm_token again")
    if stored_digest != digest:
        raise ValueError(
            "message differs from the one this confirm_token was issued for; "
            "call send_message without confirm_token to get a new one"
        )


async def send_message(
    student_alias: StudentAlias,
    title: str,
    content: str,
    recipient_ids: list[str],
    confirm_token: str | None = None,
) -> Any:
    """
    Sends a message to school staff via the Librus messaging system.
    WRITE ACTION: this delivers a real message to teachers. Disabled by default;
    enable with features.send_message in the configuration.

    Two-step confirmation: call WITHOUT confirm_token first — nothing is sent
    and you receive a preview plus a confirm_token (valid 5 minutes). Show the
    preview to the human, then call again with the exact same arguments plus
    confirm_token to actually send.
    Args:
        student_alias: The alias of the student.
        title: Message subject.
        content: Message body.
        recipient_ids: Recipient IDs from get_recipients.
        confirm_token: Token from the preview step; sending only happens when
            this is provided and matches.
    """
    LibrusManager.validate_send_message_args(student_alias, title, content, recipient_ids)
    digest = _confirmation_digest(student_alias, title, content, recipient_ids)
    if confirm_token is None:
        token = _issue_confirmation(digest)
        return {
            "status": "confirmation_required",
            "confirm_token": token,
            "expires_in_seconds": int(SEND_CONFIRMATION_TTL_SECONDS),
            "preview": {
                "student_alias": student_alias,
                "title": title,
                "content": content,
                "recipient_ids": recipient_ids,
            },
        }
    _redeem_confirmation(confirm_token, digest)
    result = await LibrusManager.send_message_to(student_alias, title, content, recipient_ids)
    return {
        "status": "sent" if result["success"] else "failed",
        "success": result["success"],
        "result": result["result"],
        "title": title,
        "recipient_count": len(recipient_ids),
    }


_FEATURE_TOOLS: dict[str, list[tuple[Any, ToolAnnotations]]] = {
    "notifications": [(get_new_notifications, LOCAL_STATE_WRITE)],
    "attachments": [(get_message_attachments, READ_ONLY), (download_attachment, LOCAL_STATE_WRITE)],
    "behaviour_notes": [(get_behaviour_notes, READ_ONLY)],
    "send_message": [
        (get_recipient_groups, READ_ONLY),
        (get_recipients, READ_ONLY),
        (send_message, SEND_MESSAGE),
    ],
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
        for tool, annotations in tools:
            if tool.__name__ in _registered_optional_tools:
                continue
            mcp.add_tool(tool, annotations=annotations)
            _registered_optional_tools.add(tool.__name__)
            registered.append(tool.__name__)
    return registered


def main():
    register_optional_tools()
    mcp.run()


if __name__ == "__main__":
    main()
