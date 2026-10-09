"""Explicit MCP projections over native types, never apix response aliases."""

from datetime import date
from typing import Annotated, Literal

from librus_python_api import (
    AttendanceRecord,
    AttendanceView,
    DescriptiveGrade,
    DescriptiveGradeSummary,
    FormativeGrade,
    GradeKind,
    GradeView,
    Identity,
    LuckyNumber,
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
    record_type: Literal["numeric", "descriptive"]
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


class FormativeItem(WireModel):
    record_type: Literal["formative"] = "formative"
    assessment: FormativeGrade


GradeRecord = GradeItem | FormativeItem


class GradesResult(WireModel):
    items: tuple[GradeRecord, ...]
    averages: tuple[SchoolAverage, ...]
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
    )
