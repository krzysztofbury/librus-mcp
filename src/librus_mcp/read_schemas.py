"""Bounded wire references and envelopes for native academic reads."""

import re
from datetime import date
from typing import Annotated, Generic, Literal, TypeVar

from librus_python_api import (
    AttendanceView,
    CompletedLesson,
    CompletedLessonsCursor,
    DetailField,
    FrequencyMeasure,
    GradeView,
    Identity,
    Observation,
    SchoolReference,
    SubjectFrequency,
    TimetableDay,
)
from pydantic import BeforeValidator, Field

from librus_mcp.config import ALIAS_PATTERN
from librus_mcp.schemas import (
    HexDigest,
    Pagination,
    WindowPagination,
    WireModel,
)

AccountAliasInput = Annotated[str, Field(min_length=1, max_length=80, pattern=ALIAS_PATTERN)]
NumericID = Annotated[str, Field(pattern=r"^[0-9]{1,64}$")]
Limit = Annotated[int, Field(strict=True, ge=1, le=256)]
MaxPages = Annotated[int, Field(strict=True, ge=1, le=8)]
T = TypeVar("T")


def civil_date(value: object) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("use an ISO civil date")
    return date.fromisoformat(value)


ISODate = Annotated[date, BeforeValidator(civil_date)]


class WindowResult(WireModel, Generic[T]):
    items: tuple[T, ...]
    date_from: date | None
    date_to: date | None
    scope: GradeView | AttendanceView
    identity: Identity
    observation: Observation
    pagination: WindowPagination


class SchoolReferenceInput(WireModel):
    context: HexDigest
    kind: Literal["agenda", "homework"]
    identifier: NumericID
    account: AccountAliasInput

    @classmethod
    def from_native(cls, value: SchoolReference, context: str) -> "SchoolReferenceInput":
        return cls(
            context=context, kind=value.kind, identifier=value.identifier, account=value.account
        )

    def native(self) -> SchoolReference:
        return SchoolReference(kind=self.kind, identifier=self.identifier, account=self.account)


class DetailData(WireModel):
    title: str | None = None
    normalized_fields: tuple[DetailField, ...]
    notes: tuple[str, ...]


class DetailResult(WireModel):
    data: DetailData
    identity: Identity
    observation: Observation


class FrequencyData(WireModel):
    first_semester: FrequencyMeasure
    second_semester: FrequencyMeasure
    overall: FrequencyMeasure


class FrequencyResult(WireModel):
    data: FrequencyData
    identity: Identity
    observation: Observation


class CollectionResult(WireModel, Generic[T]):
    items: tuple[T, ...]
    identity: Identity
    observation: Observation
    pagination: Pagination = Field(default_factory=Pagination)


class TimetableResult(CollectionResult[TimetableDay]):
    monday: date
    timezone: Literal["Europe/Warsaw"] = "Europe/Warsaw"


class SubjectFrequencyResult(CollectionResult[SubjectFrequency]):
    date_from: date | None
    date_to: date | None


class AgendaEventOutput(WireModel):
    day: date
    title: str
    subject: str | None
    text: str
    lesson_number: int | None
    # Civil time is presented verbatim in the native ISO format, never as UTC.
    at_time: str | None
    metadata_text: str
    metadata: tuple[tuple[str, str], ...]
    metadata_notes: tuple[str, ...]
    reference: SchoolReferenceInput | None


class AgendaResult(CollectionResult[AgendaEventOutput]):
    year: int
    month: int
    timezone: Literal["Europe/Warsaw"] = "Europe/Warsaw"


class HomeworkItemOutput(WireModel):
    subject: str
    teacher: str
    topic: str
    category: str
    assigned_on: date
    due_on: date
    submission_status: str | None
    marked_done_at: str | None
    reference: SchoolReferenceInput | None


class HomeworkResult(CollectionResult[HomeworkItemOutput]):
    date_from: date
    date_to: date


class LessonsCursorInput(WireModel):
    version: Literal[1] = 1
    context: HexDigest
    account: AccountAliasInput
    start: ISODate
    end: ISODate
    page: Annotated[int, Field(strict=True, ge=0, le=999)]
    offset: Annotated[int, Field(strict=True, ge=0, le=99)]
    page_count: Annotated[int, Field(strict=True, ge=1, le=1000)]
    fingerprint: HexDigest

    def native(self) -> CompletedLessonsCursor:
        return CompletedLessonsCursor(
            account=self.account,
            start=self.start,
            end=self.end,
            page=self.page,
            offset=self.offset,
            page_count=self.page_count,
            fingerprint=self.fingerprint,
        )

    @classmethod
    def from_native(cls, value: CompletedLessonsCursor, context: str) -> "LessonsCursorInput":
        return cls(
            context=context,
            account=value.account,
            start=value.start,
            end=value.end,
            page=value.page,
            offset=value.offset,
            page_count=value.page_count,
            fingerprint=value.fingerprint,
        )


class LessonsPagination(WireModel):
    next_cursor: LessonsCursorInput | None
    truncated: bool
    pages_fetched: int
    consistency: Literal["best_effort"] = "best_effort"


class LessonsResult(WireModel):
    items: tuple[CompletedLesson, ...]
    date_from: date
    date_to: date
    identity: Identity
    observation: Observation
    pagination: LessonsPagination
