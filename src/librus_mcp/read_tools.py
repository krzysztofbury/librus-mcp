"""Native academic tools; fetching, parsing and recovery belong to the API."""

from datetime import datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from librus_python_api import (
    Announcement,
    AttendanceRecord,
    AttendanceView,
    GradeView,
    HomeworkRangeRequest,
)
from librus_python_api.exceptions import ErrorKind, LibrusError
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from librus_mcp.presentation import validate_window_cursor, window_page
from librus_mcp.read_schemas import (
    AccountAliasInput,
    AgendaEventOutput,
    AgendaResult,
    CollectionResult,
    Cursor,
    DetailData,
    DetailResult,
    FetchPages,
    FirstDay,
    FrequencyData,
    FrequencyResult,
    HomeworkItemOutput,
    HomeworkResult,
    ISODate,
    LastDay,
    LessonsCursorInput,
    LessonsPagination,
    LessonsResult,
    NumericID,
    PageLimit,
    SchoolReferenceInput,
    Scope,
    SubjectFrequencyResult,
    TimetableResult,
    WindowResult,
)
from librus_mcp.runtime import Runtime
from librus_mcp.schemas import (
    FormativeItem,
    GradeRecord,
    PresentationCursor,
    descriptive_item,
    numeric_item,
)


def register_read_tools(server: MCPServer[Runtime]) -> None:
    ordinary = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    # Changes Librus's remembered view, never school data.
    selection = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
    server.tool(title="Grades by date", annotations=selection)(get_grades_window)
    server.tool(title="Attendance by date", annotations=selection)(get_attendance_window)
    server.tool(title="Attendance details", annotations=ordinary)(get_attendance_detail)
    server.tool(title="Attendance frequency", annotations=ordinary)(get_attendance_frequency)
    server.tool(title="Attendance by subject", annotations=ordinary)(get_subject_frequency)
    server.tool(title="Timetable", annotations=selection)(get_timetable)
    server.tool(title="Announcements", annotations=ordinary)(get_announcements)
    server.tool(title="Calendar", annotations=selection)(get_agenda)
    server.tool(title="Calendar event details", annotations=ordinary)(get_agenda_detail)
    server.tool(title="Homework", annotations=selection)(get_homework)
    server.tool(title="Homework details", annotations=ordinary)(get_homework_detail)
    server.tool(title="Completed lessons", annotations=selection)(get_completed_lessons)


async def get_grades_window(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
    date_from: FirstDay[ISODate | None] = None,
    date_to: LastDay[ISODate | None] = None,
    scope: Scope[GradeView] = GradeView.ALL,
    cursor: Cursor[PresentationCursor] = None,
    limit: PageLimit = 100,
) -> WindowResult[GradeRecord]:
    """List grades and formative assessments dated within date_from..date_to, without averages (see get_grades). A point grade's raw is a score on the scale its category names. scope also changes the view this login's Librus session remembers and may not apply to formative rows. A grade whose formative_id equals a formative row's assessment.detail_id is one assessment."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    validate_window_cursor(
        cursor, client.context.identifier, ("grades", scope.value, str(date_from), str(date_to))
    )
    result = await client.grades_window(
        start=date_from, end=date_to, view=scope, budget=runtime.budget
    )
    items = (
        tuple(numeric_item(item) for item in result.numeric)
        + tuple(descriptive_item(item) for item in result.descriptive)
        + tuple(FormativeItem(assessment=item) for item in result.formative)
    )
    selected, pagination = window_page(
        items,
        context=client.context.identifier,
        query=("grades", scope.value, str(date_from), str(date_to)),
        cursor=cursor,
        limit=limit,
    )
    return WindowResult[GradeRecord](
        items=selected,
        date_from=date_from,
        date_to=date_to,
        scope=scope,
        identity=result.identity,
        observation=result.observation,
        pagination=pagination,
    )


async def get_attendance_window(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
    date_from: FirstDay[ISODate | None] = None,
    date_to: LastDay[ISODate | None] = None,
    scope: Scope[AttendanceView] = AttendanceView.ALL,
    cursor: Cursor[PresentationCursor] = None,
    limit: PageLimit = 100,
) -> WindowResult[AttendanceRecord]:
    """List attendance records dated within date_from..date_to. Use this instead of get_attendance for a date range. scope also changes the view this login's Librus session remembers."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    validate_window_cursor(
        cursor, client.context.identifier, ("attendance", scope.value, str(date_from), str(date_to))
    )
    result = await client.attendance_window(
        start=date_from, end=date_to, view=scope, budget=runtime.budget
    )
    items, pagination = window_page(
        result.items,
        context=client.context.identifier,
        query=("attendance", scope.value, str(date_from), str(date_to)),
        cursor=cursor,
        limit=limit,
    )
    return WindowResult[AttendanceRecord](
        items=items,
        date_from=date_from,
        date_to=date_to,
        scope=scope,
        identity=result.identity,
        observation=result.observation,
        pagination=pagination,
    )


async def get_attendance_detail(
    account_alias: AccountAliasInput,
    attendance_id: Annotated[
        NumericID, Field(description="A record's detail_id, or a lesson's attendance_detail_id.")
    ],
    ctx: Context[Runtime, Any],
) -> DetailResult:
    """Get every field Librus shows for one attendance record, such as date and topic. The id comes from get_attendance, get_attendance_window or get_completed_lessons."""
    runtime = ctx.request_context.lifespan_context
    result = await runtime.account(account_alias).attendance_detail(
        attendance_id, budget=runtime.budget
    )
    return DetailResult(
        data=DetailData(normalized_fields=result.normalized_fields, notes=result.notes),
        identity=result.identity,
        observation=result.observation,
    )


async def get_attendance_frequency(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
) -> FrequencyResult:
    """Get attendance totals for each semester and the year: attended, total, excluded and unknown lessons, with ratios from 0 to 1 (null when undefined). For a per-subject breakdown use get_subject_frequency."""
    runtime = ctx.request_context.lifespan_context
    result = await runtime.account(account_alias).attendance_frequency(budget=runtime.budget)
    return FrequencyResult(
        data=FrequencyData(
            first_semester=result.first_semester,
            second_semester=result.second_semester,
            overall=result.overall,
        ),
        identity=result.identity,
        observation=result.observation,
    )


async def get_subject_frequency(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
    date_from: FirstDay[ISODate | None] = None,
    date_to: LastDay[ISODate | None] = None,
) -> SubjectFrequencyResult:
    """Get attendance counts and ratios per subject, optionally within a window of up to 371 days. For overall totals use get_attendance_frequency."""
    runtime = ctx.request_context.lifespan_context
    result = await runtime.account(account_alias).subject_frequency(
        start=date_from,
        end=date_to,
        budget=runtime.budget,
    )
    return SubjectFrequencyResult(
        items=result.items,
        date_from=result.start,
        date_to=result.end,
        identity=result.identity,
        observation=result.observation,
    )


async def get_timetable(
    account_alias: AccountAliasInput,
    monday: Annotated[
        ISODate, Field(description="Any date in the week, YYYY-MM-DD; the week's Monday is used.")
    ],
    ctx: Context[Runtime, Any],
) -> TimetableResult:
    """Get the lesson plan for one week, with substitutions and cancellations, in school local time. Selecting the week also changes the week this login's Librus session remembers."""
    runtime = ctx.request_context.lifespan_context
    # Agents pass "today"; the week is what they mean. The result names its Monday.
    week = monday - timedelta(days=monday.weekday())
    result = await runtime.account(account_alias).timetable(week, budget=runtime.budget)
    return TimetableResult(
        items=result.days,
        monday=result.monday,
        identity=result.identity,
        observation=result.observation,
    )


async def get_announcements(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
) -> CollectionResult[Announcement]:
    """Get all school announcements with their full text. Does not mark them read in Librus."""
    runtime = ctx.request_context.lifespan_context
    result = await runtime.account(account_alias).announcements(budget=runtime.budget)
    return CollectionResult[Announcement](
        items=result.items, identity=result.identity, observation=result.observation
    )


async def get_agenda(
    account_alias: AccountAliasInput,
    year: Annotated[int, Field(strict=True, ge=1900, le=9999, description="Calendar year.")],
    month: Annotated[int, Field(strict=True, ge=1, le=12, description="Month, 1 to 12.")],
    ctx: Context[Runtime, Any],
) -> AgendaResult:
    """List one month of school calendar events such as tests, trips and days off. Pass an event's reference, when present, to get_agenda_detail. Selecting the month also changes the month this login's Librus session remembers."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    result = await client.agenda(year, month, budget=runtime.budget)
    items = tuple(
        AgendaEventOutput(
            day=item.day,
            title=item.title,
            subject=item.subject,
            text=item.text,
            lesson_number=item.lesson_number,
            at_time=None if item.at_time is None else item.at_time.isoformat(),
            metadata_text=item.metadata_text,
            metadata=item.metadata,
            metadata_notes=item.metadata_notes,
            reference=None
            if item.reference is None
            else SchoolReferenceInput.from_native(item.reference, client.context.identifier),
        )
        for day in result.days
        for item in day.events
    )
    return AgendaResult(
        items=items,
        year=result.year,
        month=result.month,
        identity=result.identity,
        observation=result.observation,
    )


def require_school_reference(
    reference: SchoolReferenceInput,
    runtime: Runtime,
    alias: str,
    kind: str,
) -> None:
    if reference.context != runtime.account(alias).context.identifier or reference.account != alias:
        raise LibrusError(ErrorKind.INVALID_INPUT)
    if reference.kind != kind:
        raise LibrusError(ErrorKind.INVALID_INPUT)


async def get_agenda_detail(
    account_alias: AccountAliasInput,
    event_ref: Annotated[
        SchoolReferenceInput, Field(description="An event's reference from get_agenda, unchanged.")
    ],
    ctx: Context[Runtime, Any],
) -> DetailResult:
    """Get every detail of one calendar event. Use the same account_alias that get_agenda used."""
    runtime = ctx.request_context.lifespan_context
    require_school_reference(event_ref, runtime, account_alias, "agenda")
    result = await runtime.account(account_alias).agenda_detail(
        event_ref.native(), budget=runtime.budget
    )
    return DetailResult(
        data=DetailData(
            title=result.title,
            normalized_fields=result.normalized_fields,
            notes=result.notes,
        ),
        identity=result.identity,
        observation=result.observation,
    )


async def get_homework(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
    date_from: FirstDay[ISODate | None] = None,
    date_to: LastDay[ISODate | None] = None,
) -> HomeworkResult:
    """List homework in a date range; give both dates or neither (today to 14 days ahead, Warsaw time). Pass an item's reference to get_homework_detail. The range also changes what this login's Librus session remembers."""
    runtime = ctx.request_context.lifespan_context
    if (date_from is None) != (date_to is None):
        raise LibrusError(ErrorKind.INVALID_INPUT)
    if date_from is None or date_to is None:
        date_from = datetime.now(ZoneInfo("Europe/Warsaw")).date()
        date_to = date_from + timedelta(days=14)
    client = runtime.account(account_alias)
    result = await client.homework_range(
        HomeworkRangeRequest(date_from, date_to), budget=runtime.budget
    )
    items = tuple(
        HomeworkItemOutput(
            subject=item.subject,
            teacher=item.teacher,
            topic=item.topic,
            category=item.category,
            assigned_on=item.assigned_on,
            due_on=item.due_on,
            submission_status=item.submission_status,
            marked_done_at=None if item.marked_done_at is None else item.marked_done_at.isoformat(),
            reference=None
            if item.reference is None
            else SchoolReferenceInput.from_native(item.reference, client.context.identifier),
        )
        for item in result.items
    )
    return HomeworkResult(
        items=items,
        date_from=result.start,
        date_to=result.end,
        identity=result.identity,
        observation=result.observation,
    )


async def get_homework_detail(
    account_alias: AccountAliasInput,
    homework_ref: Annotated[
        SchoolReferenceInput, Field(description="An item's reference from get_homework, unchanged.")
    ],
    ctx: Context[Runtime, Any],
) -> DetailResult:
    """Get the full text of one homework assignment. Does not mark it read in Librus."""
    runtime = ctx.request_context.lifespan_context
    require_school_reference(homework_ref, runtime, account_alias, "homework")
    result = await runtime.account(account_alias).homework_detail(
        homework_ref.native(), budget=runtime.budget
    )
    return DetailResult(
        data=DetailData(
            title=result.title,
            normalized_fields=result.normalized_fields,
            notes=result.notes,
        ),
        identity=result.identity,
        observation=result.observation,
    )


async def get_completed_lessons(
    account_alias: AccountAliasInput,
    date_from: FirstDay[ISODate],
    date_to: LastDay[ISODate],
    ctx: Context[Runtime, Any],
    cursor: Cursor[LessonsCursorInput] = None,
    limit: PageLimit = 100,
    max_pages: FetchPages = 2,
) -> LessonsResult:
    """List lessons already held between two dates: subject, teacher, topic and attendance mark. Continue with the returned cursor and the same dates. The range also changes what this login's Librus session remembers."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    if cursor is not None and cursor.context != client.context.identifier:
        raise LibrusError(ErrorKind.INVALID_INPUT)
    result = await client.completed_lessons(
        date_from,
        date_to,
        cursor=None if cursor is None else cursor.native(),
        limit=limit,
        max_pages=max_pages,
        budget=runtime.budget,
    )
    next_cursor = (
        None
        if result.next_cursor is None
        else LessonsCursorInput.from_native(result.next_cursor, client.context.identifier)
    )
    return LessonsResult(
        items=result.items,
        date_from=result.start,
        date_to=result.end,
        identity=result.identity,
        observation=result.observation,
        pagination=LessonsPagination(
            next_cursor=next_cursor,
            truncated=next_cursor is not None,
            pages_fetched=result.pages_fetched,
        ),
    )
