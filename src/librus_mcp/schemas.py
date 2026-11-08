"""Explicit MCP projections over native types, never apix response aliases."""

from collections.abc import Sequence
from datetime import date
from typing import Annotated, Literal

from librus_python_api import (
    AttendanceRecord,
    AttendanceView,
    DescriptiveGrade,
    DescriptiveGradeSummary,
    FormativeGrade,
    GradeCorrection,
    GradeKind,
    GradeView,
    Identity,
    LuckyNumber,
    NumericGrade,
    Observation,
    SchoolAverage,
    SubjectGradeSummary,
)
from pydantic import BaseModel, ConfigDict, Field


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


HexDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PresentationCursor(WireModel):
    version: Literal[1] = 1
    context: HexDigest
    query: HexDigest
    source: HexDigest
    offset: Annotated[int, Field(strict=True, ge=1, le=4096)]


class WindowPagination(WireModel):
    next_cursor: PresentationCursor | None
    truncated: bool
    reason: Literal["item_limit"] | None
    consistency: Literal["best_effort"] = "best_effort"


class SizedWindowPagination(WireModel):
    # Only tools whose single items can be large also end a page by size.
    next_cursor: PresentationCursor | None
    truncated: bool
    reason: Literal["item_limit", "size_limit"] | None
    consistency: Literal["best_effort"] = "best_effort"


class Pagination(WireModel):
    next_cursor: None = None
    truncated: Literal[False] = False
    consistency: Literal["best_effort"] = "best_effort"


class AccountAlias(WireModel):
    account_alias: str


class AccountsResult(WireModel):
    items: tuple[AccountAlias, ...]


class ProfileData(WireModel):
    identity: Identity
    name: str
    class_name: str
    register_number: int
    tutor: str
    school: str
    lucky_number: LuckyNumber


class ProfileResult(WireModel):
    data: ProfileData
    observation: Observation


class FinalGradesResult(WireModel):
    items: tuple[SubjectGradeSummary, ...]
    identity: Identity
    observation: Observation
    pagination: Pagination = Field(default_factory=Pagination)


class GradeItem(WireModel):
    # Suppress inert HTML hrefs; no grade-detail tool accepts raw routes in 2.0.
    record_type: Literal["numeric", "point", "descriptive"]
    subject: str
    raw: str
    day: date
    semester: Literal[0, 1, 2] | None
    kind: GradeKind
    teacher: str | None
    comment: str | None
    metadata: tuple[tuple[str, str], ...]
    counts_toward_average: bool | None = None
    weight: int | None = None
    category: str | None = None
    formative_id: str | None = None
    grade_id: str | None = None
    corrects: tuple[str, ...] | None = None
    corrected_by: tuple[str, ...] | None = None


class FormativeItem(WireModel):
    record_type: Literal["formative"] = "formative"
    assessment: FormativeGrade


GradeRecord = GradeItem | FormativeItem


class GradesResult(WireModel):
    items: tuple[GradeRecord, ...]
    averages: tuple[SchoolAverage, ...]
    point_results: tuple[SchoolAverage, ...]
    descriptive_summaries: tuple[DescriptiveGradeSummary, ...]
    scope: GradeView
    identity: Identity
    observation: Observation
    pagination: WindowPagination


class AttendanceResult(WireModel):
    items: tuple[AttendanceRecord, ...]
    semesters: tuple[Literal[1, 2], ...]
    scope: AttendanceView
    identity: Identity
    observation: Observation
    pagination: WindowPagination


def descriptive_item(record: DescriptiveGrade) -> GradeItem:
    return GradeItem(
        record_type="descriptive",
        subject=record.subject,
        raw=record.raw,
        day=record.day,
        semester=record.semester,
        kind=record.kind,
        teacher=record.teacher,
        comment=record.comment,
        metadata=record.metadata,
        formative_id=record.formative_id,
        grade_id=record.grade_id,
    )


def numeric_item(record: NumericGrade) -> GradeItem:
    return GradeItem(
        record_type="numeric" if record.point_grade_id is None else "point",
        subject=record.subject,
        raw=record.raw,
        day=record.day,
        semester=record.semester,
        kind=record.kind,
        teacher=record.teacher,
        comment=record.comment,
        metadata=record.metadata,
        counts_toward_average=record.counts_toward_average,
        weight=record.weight,
        category=record.category,
        formative_id=record.formative_id,
        grade_id=record.grade_id,
    )


_SEMESTER_ORDER = {1: 0, 2: 1, 0: 2, None: 3}


def grade_items(
    numeric: Sequence[NumericGrade],
    descriptive: Sequence[DescriptiveGrade],
    formative: Sequence[FormativeGrade],
    corrections: Sequence[GradeCorrection] = (),
    scope: GradeView = GradeView.ALL,
) -> tuple[GradeRecord, ...]:
    """Numeric, descriptive, then formative items in an order stable across reads.

    Librus may list the grades of one cell in a different order on each read
    (observed 2026-11-06), which made every continuation cursor stale. Each
    group keeps the page's subject order; within a subject, items follow
    semester, day and then their full content.

    `corrections` are the page's correction brackets (#88). Links are known
    only in the all scope, the one seen to show brackets, and only for items
    with a `grade_id`; elsewhere `corrects` and `corrected_by` stay null.
    """
    links: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for bracket in corrections:
        ids = bracket.grade_ids
        for position, grade_id in enumerate(ids):
            links[grade_id] = ids[:position], ids[position + 1 :]

    def linked(item: GradeItem) -> GradeItem:
        if scope is not GradeView.ALL or item.grade_id is None:
            return item
        earlier, later = links.get(item.grade_id, ((), ()))
        return item.model_copy(update={"corrects": earlier, "corrected_by": later})

    result: list[GradeRecord] = []
    groups: tuple[list[GradeRecord], ...] = (
        [linked(numeric_item(record)) for record in numeric],
        [linked(descriptive_item(record)) for record in descriptive],
        [FormativeItem(assessment=record) for record in formative],
    )
    for group in groups:
        rank: dict[str, int] = {}
        keys = []
        for item in group:
            record = item.assessment if isinstance(item, FormativeItem) else item
            rank.setdefault(record.subject, len(rank))
            keys.append(
                (
                    rank[record.subject],
                    _SEMESTER_ORDER[record.semester],
                    record.day,
                    item.model_dump_json(),
                )
            )
        result.extend(item for _, item in sorted(zip(keys, group), key=lambda pair: pair[0]))
    return tuple(result)
