"""Explicit MCP projections over native types, never apix response aliases."""

from datetime import date
from typing import Literal

from librus_python_api import (
    AttendanceRecord,
    AttendanceView,
    DescriptiveGrade,
    DescriptiveGradeSummary,
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


class GradesResult(WireModel):
    items: tuple[GradeItem, ...]
    averages: tuple[SchoolAverage, ...]
    descriptive_summaries: tuple[DescriptiveGradeSummary, ...]
    scope: GradeView
    identity: Identity
    observation: Observation
    pagination: Pagination = Field(default_factory=Pagination)


class AttendanceResult(WireModel):
    items: tuple[AttendanceRecord, ...]
    semesters: tuple[Literal[1, 2], ...]
    scope: AttendanceView
    identity: Identity
    observation: Observation
    pagination: Pagination = Field(default_factory=Pagination)


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
    )
