import dataclasses
import hashlib
import json
import secrets
import sys
import time
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from src import __version__
from src.config import ALIAS_PATTERN, MAX_ALIAS_LENGTH, ConfigError
from src.librus_client import (
    MAX_ALL_MESSAGE_ITEMS,
    MAX_ALL_MESSAGE_PAGES,
    MAX_COMPLETED_LESSONS_ITEMS,
    MAX_COMPLETED_LESSONS_PAGES,
    MAX_LESSON_WINDOW_ITEMS,
    MAX_LESSON_WINDOW_PAGES,
    MAX_RECIPIENT_ID_LENGTH,
    MAX_SEND_CONTENT_LENGTH,
    MAX_SEND_RECIPIENTS,
    MAX_SEND_TITLE_LENGTH,
    MESSAGES_PER_PAGE,
    LibrusManager,
)
from src.output_models import (
    AnnouncementOutput,
    AttachmentOutput,
    AttendanceFrequencyOutput,
    AttendanceOutput,
    BehaviourNoteOutput,
    CompletedLessonOutput,
    CompletedLessonsPageOutput,
    DetailFieldsOutput,
    DownloadOutput,
    FinalGradeOutput,
    GradesOutput,
    HomeworkOutput,
    MessageContentOutput,
    MessagesOutput,
    NotificationsOutput,
    PeriodOutput,
    RecentScheduleEventOutput,
    ScheduleOutput,
    SendMessageOutput,
    StudentInformationOutput,
    SubjectFrequencyOutput,
)

# Passing version explicitly: an unversioned server advertises an empty version
# in the initialize handshake, so hosts would show no version for this server.
mcp = MCPServer("librus-mcp", version=__version__)

# Every tool talks to the external Librus service, hence open_world_hint on all.
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
# Mutates local state or consumes a read-once upstream view, but does not change
# school records; repeated calls can therefore yield different results.
LOCAL_STATE_WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)
SEND_MESSAGE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True
)

StudentAlias = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAX_ALIAS_LENGTH,
        pattern=ALIAS_PATTERN,
        description="Alias of the student account",
    ),
]
# Message and file identifiers are bare numeric path segments in Synergia.
NumericId = Annotated[str, Field(pattern=r"^\d+$")]
MessageTitle = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAX_SEND_TITLE_LENGTH,
        description="Nonblank subject; the combined UTF-8 message payload is limited to 64 KiB",
    ),
]
MessageContent = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAX_SEND_CONTENT_LENGTH,
        description="Nonblank body; the combined UTF-8 message payload is limited to 64 KiB",
    ),
]
RecipientId = Annotated[
    str,
    Field(min_length=1, max_length=MAX_RECIPIENT_ID_LENGTH, pattern=r"^[0-9]+$"),
]
RecipientIds = Annotated[
    list[RecipientId],
    Field(
        min_length=1,
        max_length=MAX_SEND_RECIPIENTS,
        description="Unique numeric recipient IDs; included in the 64 KiB payload limit",
        json_schema_extra={"uniqueItems": True},
    ),
]
IsoDate = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
SortBy = Literal["all", "week", "last_login"]

# MCPServer uses return annotations to publish and validate output schemas.
# Return the original dictionaries and lists so its legacy text content stays
# unchanged; the SDK separately validates and emits structuredContent.


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
    """List configured student aliases."""
    return LibrusManager.list_accounts()


@mcp.tool(annotations=READ_ONLY)
async def get_grades(student_alias: StudentAlias, sort_by: SortBy = "all") -> GradesOutput:
    """Get numeric, GPA and descriptive grades. sort_by filters to all, this week or since last login."""
    grades = await LibrusManager.fetch_grades(student_alias, sort_by)
    return to_dict(grades)


@mcp.tool(annotations=READ_ONLY)
async def get_messages(
    student_alias: StudentAlias,
    page: Annotated[int, Field(ge=0, le=1000)] = 0,
    folder: Literal["received", "sent"] = "received",
    all_pages: bool = False,
    limit: Annotated[int | None, Field(ge=1, le=MAX_ALL_MESSAGE_ITEMS)] = None,
    max_pages: Annotated[int | None, Field(ge=1, le=MAX_ALL_MESSAGE_PAGES)] = None,
    offset: Annotated[int, Field(ge=0, lt=MESSAGES_PER_PAGE)] = 0,
) -> MessagesOutput:
    """Get received or sent messages, newest first. Page 0 is newest; pages hold
    50. For bounded reads set limit or max_pages; resume with next_page and
    next_offset. Sent max_page=null means the last page is unknown. Legacy
    all_pages ignores page and fetches up to 2000 messages without a cursor.
    """
    if all_pages:
        if limit is not None or max_pages is not None or offset:
            raise ValueError("all_pages cannot be combined with limit, max_pages or offset")
        messages = await LibrusManager.fetch_all_messages(student_alias, folder)
    elif limit is not None or max_pages is not None or offset:
        messages = await LibrusManager.fetch_message_window(
            student_alias,
            page,
            folder,
            offset,
            limit if limit is not None else MAX_ALL_MESSAGE_ITEMS,
            max_pages if max_pages is not None else MAX_ALL_MESSAGE_PAGES,
        )
    else:
        messages = await LibrusManager.fetch_messages(student_alias, page, folder)
    return to_dict(messages)


@mcp.tool(annotations=READ_ONLY)
async def get_message_content(
    student_alias: StudentAlias, message_id: NumericId
) -> MessageContentOutput:
    """Get full message content by numeric ID from get_messages.href."""
    return await LibrusManager.fetch_message_content(student_alias, message_id)


@mcp.tool(annotations=READ_ONLY)
async def get_attendance(
    student_alias: StudentAlias, sort_by: SortBy = "all"
) -> list[list[AttendanceOutput]]:
    """Get attendance by semester. sort_by filters to all, this week or since last login."""
    attendance = await LibrusManager.fetch_attendance(student_alias, sort_by)
    return to_dict(attendance)


@mcp.tool(annotations=READ_ONLY)
async def get_attendance_detail(
    student_alias: StudentAlias, detail_url: NumericId
) -> DetailFieldsOutput:
    """Get attendance entry details by numeric ID from get_attendance.href."""
    detail = await LibrusManager.fetch_attendance_detail(student_alias, detail_url)
    return to_dict(detail)


@mcp.tool(annotations=READ_ONLY)
async def get_attendance_frequency(student_alias: StudentAlias) -> AttendanceFrequencyOutput:
    """Get first-semester, second-semester and overall attendance ratios (0 to 1)."""
    return await LibrusManager.fetch_attendance_frequency(student_alias)


@mcp.tool(annotations=READ_ONLY)
async def get_subject_frequency(
    student_alias: StudentAlias,
    start: IsoDate | None = None,
    end: IsoDate | None = None,
) -> SubjectFrequencyOutput:
    """Get per-subject attendance percentages (0 to 100), optionally by date range."""
    frequency = await LibrusManager.fetch_subject_frequency(student_alias, start, end)
    return to_dict(frequency)


@mcp.tool(annotations=READ_ONLY)
async def get_homework(
    student_alias: StudentAlias,
    date_from: IsoDate | None = None,
    date_to: IsoDate | None = None,
) -> list[HomeworkOutput]:
    """Get homework for the next two weeks, or supply both dates (at most 370 days apart)."""
    homework = await LibrusManager.fetch_homework(student_alias, date_from, date_to)
    return to_dict(homework)


@mcp.tool(annotations=READ_ONLY)
async def get_homework_detail(
    student_alias: StudentAlias, detail_url: NumericId
) -> DetailFieldsOutput:
    """Get homework details by numeric ID from get_homework.href."""
    detail = await LibrusManager.fetch_homework_detail(student_alias, detail_url)
    return to_dict(detail)


@mcp.tool(annotations=READ_ONLY)
async def get_schedule(
    student_alias: StudentAlias,
    year: Annotated[str, Field(pattern=r"^\d{4}$")],
    month: Annotated[str, Field(pattern=r"^\d{1,2}$")],
) -> ScheduleOutput:
    """Get calendar events and exams for a year and month."""
    schedule = await LibrusManager.fetch_schedule(student_alias, month, year)
    return to_dict(schedule)


@mcp.tool(annotations=READ_ONLY)
async def get_schedule_detail(student_alias: StudentAlias, href: str) -> DetailFieldsOutput:
    """Get event details by href from get_schedule or get_recent_schedule_events."""
    detail = await LibrusManager.fetch_schedule_detail(student_alias, href)
    return to_dict(detail)


@mcp.tool(annotations=READ_ONLY)
async def get_timetable(
    student_alias: StudentAlias, monday: IsoDate | None = None
) -> list[list[PeriodOutput]]:
    """Get one week's lessons; monday defaults to this week and must be a Monday."""
    timetable = await LibrusManager.fetch_timetable(student_alias, monday)
    return to_dict(timetable)


@mcp.tool(annotations=READ_ONLY)
async def get_announcements(student_alias: StudentAlias) -> list[AnnouncementOutput]:
    """Get school announcements."""
    announcements = await LibrusManager.fetch_announcements(student_alias)
    return to_dict(announcements)


@mcp.tool(annotations=READ_ONLY)
async def get_completed_lessons(
    student_alias: StudentAlias, date_from: IsoDate, date_to: IsoDate
) -> list[CompletedLessonOutput]:
    """Get completed lesson subjects, teachers and topics within a date range."""
    lessons = await LibrusManager.fetch_completed_lessons(student_alias, date_from, date_to)
    return to_dict(lessons)


@mcp.tool(annotations=READ_ONLY)
async def get_completed_lessons_page(
    student_alias: StudentAlias,
    date_from: IsoDate,
    date_to: IsoDate,
    page: Annotated[int, Field(ge=0, lt=MAX_COMPLETED_LESSONS_PAGES)] = 0,
    offset: Annotated[int, Field(ge=0, lt=MAX_COMPLETED_LESSONS_ITEMS)] = 0,
    limit: Annotated[int, Field(ge=1, le=MAX_LESSON_WINDOW_ITEMS)] = 100,
    max_pages: Annotated[int, Field(ge=1, le=MAX_LESSON_WINDOW_PAGES)] = 1,
) -> CompletedLessonsPageOutput:
    """Get a bounded batch of completed lessons. Continue with next_page and
    next_offset, keeping the same dates. The legacy get_completed_lessons tool
    still returns a plain list.
    """
    result = await LibrusManager.fetch_completed_lessons_page(
        student_alias, date_from, date_to, page, offset, limit, max_pages
    )
    return to_dict(result)


@mcp.tool(annotations=READ_ONLY)
async def get_student_information(student_alias: StudentAlias) -> StudentInformationOutput:
    """Get student name, class, tutor, school and lucky number."""
    info = await LibrusManager.fetch_student_information(student_alias)
    return to_dict(info)


@mcp.tool(annotations=READ_ONLY)
async def get_final_grades(student_alias: StudentAlias) -> list[FinalGradeOutput]:
    """Get midterm, predicted annual and final grades per subject; '-' means not issued."""
    grades = await LibrusManager.fetch_final_grades(student_alias)
    return to_dict(grades)


@mcp.tool(annotations=LOCAL_STATE_WRITE)
async def get_recent_schedule_events(
    student_alias: StudentAlias,
) -> list[RecentScheduleEventOutput]:
    """Get events added since last login. Reading consumes Librus's one-time
    view; events are checkpointed locally and may replay after interruption.
    """
    events = await LibrusManager.fetch_recent_schedule_events(student_alias)
    return to_dict(events)


# --- Optional tools, registered by register_optional_tools() based on config features ---


async def get_new_notifications(student_alias: StudentAlias) -> NotificationsOutput:
    """Get new grades, attendance, messages, announcements, events and homework.
    Advances local seen state; first_run returns the baseline since last login.
    Interrupted read-once schedule events may replay.
    """
    result = await LibrusManager.fetch_new_notifications(student_alias)
    return to_dict(result)


async def get_message_attachments(
    student_alias: StudentAlias, message_id: NumericId
) -> list[AttachmentOutput]:
    """List message attachments and file IDs by numeric message ID."""
    attachments = await LibrusManager.fetch_message_attachments(student_alias, message_id)
    return to_dict(attachments)


async def download_attachment(
    student_alias: StudentAlias, message_id: NumericId, file_id: NumericId
) -> DownloadOutput:
    """Download a message file by numeric IDs. Returns a server-local path,
    filename, size and content type; never overwrites an existing file.
    """
    info = await LibrusManager.download_message_attachment(student_alias, message_id, file_id)
    return to_dict(info)


async def get_behaviour_notes(student_alias: StudentAlias) -> list[BehaviourNoteOutput]:
    """Get experimental behaviour notes (uwagi), or [] when none exist."""
    notes = await LibrusManager.fetch_behaviour_notes(student_alias)
    return to_dict(notes)


async def get_recipient_groups(student_alias: StudentAlias) -> list[str]:
    """List messaging recipient group IDs."""
    groups = await LibrusManager.fetch_recipient_groups(student_alias)
    return to_dict(groups)


async def get_recipients(student_alias: StudentAlias, group: str) -> dict[str, str]:
    """List recipient names and IDs in a group from get_recipient_groups."""
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
    title: MessageTitle,
    content: MessageContent,
    recipient_ids: RecipientIds,
    confirm_token: str | None = None,
) -> SendMessageOutput:
    """WRITE ACTION, disabled by default. First call without confirm_token
    sends nothing: show the preview to the human. Only a second call with the
    same payload and single-use token (valid 5 minutes) sends to recipient_ids
    from get_recipients. If delivery is uncertain, check the sent folder;
    never blindly retry.
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
    try:
        result = await LibrusManager.send_message_to(student_alias, title, content, recipient_ids)
    except RuntimeError as error:
        # A sent POST cannot safely be retried. Keep uncertainty on the MCP
        # error channel, with actionable text rather than a generic crash.
        raise ToolError(
            "Librus send delivery is uncertain; check the sent folder before trying again."
        ) from error
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


def main() -> None:
    try:
        register_optional_tools()
    except ConfigError as error:
        print(f"librus-mcp: configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    mcp.run()


if __name__ == "__main__":
    main()
