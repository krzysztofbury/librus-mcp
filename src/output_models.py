"""Published MCP response shapes; values returned by existing tools remain unchanged."""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializerFunctionWrapHandler,
    model_serializer,
)


class OutputModel(BaseModel):
    # The upstream scraper can add fields without changing the existing MCP
    # response. Keep them in structuredContent rather than silently dropping them.
    model_config = ConfigDict(extra="allow")


class GradeOutput(OutputModel):
    title: str
    grade: str
    counts: bool
    date: str
    href: str
    desc: str
    semester: int
    category: str
    teacher: str
    weight: int


class GpaOutput(OutputModel):
    semester: int
    gpa: float | str
    subject: str


class DescriptiveGradeOutput(OutputModel):
    title: str
    grade: str
    date: str
    href: str
    desc: str
    semester: int
    teacher: str


class GradesOutput(OutputModel):
    numeric: list[dict[str, list[GradeOutput]]]
    gpa: dict[str, list[GpaOutput]]
    descriptive: list[dict[str, list[DescriptiveGradeOutput]]]


class MessageOutput(OutputModel):
    author: str
    title: str
    date: str
    href: str
    unread: bool
    has_attachment: bool


class MessagesOutput(OutputModel):
    messages: list[MessageOutput]
    folder: Literal["received", "sent"]
    truncated: bool
    page: int | None = None
    max_page: int | None = None
    pages_fetched: int | None = None
    offset: int | None = None
    next_page: int | None = None
    next_offset: int | None = None

    @model_serializer(mode="wrap")
    def preserve_variant_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Preserve absent keys in legacy modes; bounded mode adds a cursor.
        return {key: value for key, value in handler(self).items() if key in self.model_fields_set}


class MessageContentOutput(OutputModel):
    author: str
    title: str
    date: str
    content: str


class AttendanceOutput(OutputModel):
    symbol: str
    href: str
    semester: int
    date: str
    type: str
    teacher: str
    period: int
    excursion: bool
    topic: str
    subject: str


class AttendanceFrequencyOutput(OutputModel):
    first_semester: float
    second_semester: float
    overall: float


class SubjectFrequencyOutput(RootModel[dict[str, float]]):
    pass


class HomeworkOutput(OutputModel):
    lesson: str
    teacher: str
    subject: str
    category: str
    task_date: str
    completion_date: str
    href: str


class DetailFieldsOutput(RootModel[dict[str, str]]):
    """Label/value detail pages use upstream Polish keys, not fixed field names."""


class ScheduleEventOutput(OutputModel):
    title: str
    subject: str
    data: dict[str, str]
    day: str
    number: int | str
    hour: str
    href: str


class ScheduleOutput(RootModel[dict[int, list[ScheduleEventOutput]]]):
    """Day keys are integers in Python and strings in the JSON response."""


class PeriodOutput(OutputModel):
    subject: str
    teacher_and_classroom: str
    date: str
    date_from: str
    date_to: str
    weekday: str
    info: dict[str, str | dict[str, str]]
    number: int
    next_recess_from: str | None
    next_recess_to: str | None


class AnnouncementOutput(OutputModel):
    title: str
    author: str
    description: str
    date: str


class CompletedLessonOutput(OutputModel):
    subject: str
    teacher: str
    topic: str
    z_value: str
    attendance_symbol: str
    attendance_href: str
    lesson_number: int
    weekday: str
    date: str


class CompletedLessonsPageOutput(OutputModel):
    lessons: list[CompletedLessonOutput]
    page: int
    offset: int
    max_page: int
    pages_fetched: int
    next_page: int | None
    next_offset: int | None
    truncated: bool


class StudentInformationOutput(OutputModel):
    name: str
    class_name: str
    number: int
    tutor: str
    school: str
    lucky_number: int | str


class FinalGradeOutput(OutputModel):
    subject: str
    midterm: str
    predicted_final: str
    final: str


class RecentScheduleEventOutput(OutputModel):
    date_added: str
    type: str
    data: str


class NotificationDataOutput(OutputModel):
    grades: list[GradeOutput]
    attendance: list[AttendanceOutput]
    messages: list[MessageOutput]
    announcements: list[AnnouncementOutput]
    schedule: list[RecentScheduleEventOutput]
    homework: list[HomeworkOutput]


class NotificationsOutput(OutputModel):
    first_run: bool
    new: NotificationDataOutput


class AttachmentOutput(OutputModel):
    filename: str
    message_id: str
    file_id: str


class DownloadOutput(OutputModel):
    path: str
    filename: str
    size: int
    content_type: str


class BehaviourNoteOutput(OutputModel):
    date: str
    teacher: str
    category: str
    content: str


class SendPreviewDetails(OutputModel):
    student_alias: str
    title: str
    content: str
    recipient_ids: list[str]


class SendPreviewOutput(OutputModel):
    status: Literal["confirmation_required"]
    confirm_token: str
    expires_in_seconds: int
    preview: SendPreviewDetails


class SendSucceededOutput(OutputModel):
    status: Literal["sent"]
    success: Literal[True]
    result: str
    title: str
    recipient_count: int


class SendFailedOutput(OutputModel):
    status: Literal["failed"]
    success: Literal[False]
    result: str
    title: str
    recipient_count: int


class SendMessageOutput(
    RootModel[
        Annotated[
            SendPreviewOutput | SendSucceededOutput | SendFailedOutput,
            Field(discriminator="status"),
        ]
    ]
):
    """Non-error results; uncertain delivery is an MCP isError result."""

    # MCP's outputSchema requires an explicit top-level object type. Pydantic
    # emits oneOf without it for a discriminated RootModel of object variants.
    model_config = ConfigDict(json_schema_extra={"type": "object"})
