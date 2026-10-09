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
    DetailData,
    DetailResult,
    FrequencyData,
    FrequencyResult,
    HomeworkItemOutput,
    HomeworkResult,
    ISODate,
    LessonsCursorInput,
    LessonsPagination,
    LessonsResult,
    Limit,
    MaxPages,
    NumericID,
    SchoolReferenceInput,
    SubjectFrequencyResult,
    TimetableResult,
    WindowResult,
)
from librus_mcp.runtime import Runtime
from librus_mcp.schemas import (
    FormativeItem,
    GradeItem,
    GradeRecord,
    PresentationCursor,
    descriptive_item,
)


def register_read_tools(server: MCPServer[Runtime]) -> None:
    ordinary = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    selection = ToolAnnotations(read_only_hint=False, open_world_hint=True)
    server.tool(annotations=selection)(get_grades_window)
    server.tool(annotations=selection)(get_attendance_window)
    server.tool(annotations=ordinary)(get_attendance_detail)
    server.tool(annotations=ordinary)(get_attendance_frequency)
    server.tool(annotations=ordinary)(get_subject_frequency)
    server.tool(annotations=selection)(get_timetable)
    server.tool(annotations=ordinary)(get_announcements)
    server.tool(annotations=selection)(get_agenda)
    server.tool(annotations=ordinary)(get_agenda_detail)
    server.tool(annotations=selection)(get_homework)
    server.tool(annotations=ordinary)(get_homework_detail)
    server.tool(annotations=selection)(get_completed_lessons)


async def get_grades_window(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
    date_from: ISODate | None = None,
    date_to: ISODate | None = None,
    scope: GradeView = GradeView.ALL,
    cursor: PresentationCursor | None = None,
    limit: Limit = 100,
) -> WindowResult[GradeRecord]:
    """Page dated grades and formative assessments. Match formative_id to assessment.detail_id for mirrors. Dates filter both; formative scope semantics are unverified. Cursors reject source drift."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    validate_window_cursor(
        cursor, client.context.identifier, ("grades", scope.value, str(date_from), str(date_to))
    )
    result = await client.grades_window(
        start=date_from, end=date_to, view=scope, budget=runtime.budget
    )
    items = (
        tuple(
            GradeItem(
                record_type="numeric",
                subject=item.subject,
                raw=item.raw,
                day=item.day,
                semester=item.semester,
                kind=item.kind,
                teacher=item.teacher,
                comment=item.comment,
                metadata=item.metadata,
                counts_toward_average=item.counts_toward_average,
                weight=item.weight,
                category=item.category,
                formative_id=item.formative_id,
            )
            for item in result.numeric
        )
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
    date_from: ISODate | None = None,
    date_to: ISODate | None = None,
    scope: AttendanceView = AttendanceView.ALL,
    cursor: PresentationCursor | None = None,
    limit: Limit = 100,
) -> WindowResult[AttendanceRecord]:
    """Page dated attendance locally; changed source data invalidates continuation."""
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
    attendance_id: NumericID,
    ctx: Context[Runtime, Any],
) -> DetailResult:
    """Read normalized attendance detail fields for a numeric record ID."""
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
    """Read attended/total/excluded/unknown counts and ratios in 0..1 or null."""
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
    date_from: ISODate | None = None,
    date_to: ISODate | None = None,
) -> SubjectFrequencyResult:
    """Read per-subject native ratios/counts in an inclusive civil-date window."""
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
    monday: ISODate,
    ctx: Context[Runtime, Any],
) -> TimetableResult:
    """Select a Monday-starting week; return school wall-time periods and changes."""
    runtime = ctx.request_context.lifespan_context
    result = await runtime.account(account_alias).timetable(monday, budget=runtime.budget)
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
    """Read complete inert announcement text without marking it read."""
    runtime = ctx.request_context.lifespan_context
    result = await runtime.account(account_alias).announcements(budget=runtime.budget)
    return CollectionResult[Announcement](
        items=result.items, identity=result.identity, observation=result.observation
    )


async def get_agenda(
    account_alias: AccountAliasInput,
    year: Annotated[int, Field(strict=True, ge=1900, le=9999)],
    month: Annotated[int, Field(strict=True, ge=1, le=12)],
    ctx: Context[Runtime, Any],
) -> AgendaResult:
    """Read a calendar month, with account/context-bound event references."""
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
    event_ref: SchoolReferenceInput,
    ctx: Context[Runtime, Any],
) -> DetailResult:
    """Read normalized event detail from a bound reference returned by get_agenda."""
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
    date_from: ISODate | None = None,
    date_to: ISODate | None = None,
) -> HomeworkResult:
    """Read a bounded homework range; omitted dates select today through today+14 in Warsaw."""
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
    homework_ref: SchoolReferenceInput,
    ctx: Context[Runtime, Any],
) -> DetailResult:
    """Read homework detail without the separate upstream mark-read request."""
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
    date_from: ISODate,
    date_to: ISODate,
    ctx: Context[Runtime, Any],
    cursor: LessonsCursorInput | None = None,
    limit: Limit = 100,
    max_pages: MaxPages = 2,
) -> LessonsResult:
    """Read a bounded native lesson batch; continuation is account/date-bound and best effort."""
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
