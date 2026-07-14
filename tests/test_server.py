"""Tests for all MCP tools exposed by the librus-mcp server."""

import dataclasses
from collections import defaultdict
from unittest.mock import AsyncMock, patch

import pytest

from src.server import (
    get_announcements,
    get_attendance,
    get_completed_lessons,
    get_grades,
    get_homework,
    get_homework_detail,
    get_message_content,
    get_messages,
    get_schedule,
    get_student_information,
    get_subject_frequency,
    get_timetable,
    list_students,
    to_dict,
)


# --- Fake dataclasses mirroring librus-apix shapes ---


@dataclasses.dataclass
class FakeGrade:
    subject: str
    grade: str
    counts: bool
    date: str
    href: str
    desc: str
    semester: int
    category: str
    teacher: str
    weight: int


@dataclasses.dataclass
class FakeGpa:
    semester: int
    gpa: float
    subject: str


@dataclasses.dataclass
class FakeMessage:
    author: str
    title: str
    date: str
    href: str


@dataclasses.dataclass
class FakeMessageData:
    author: str
    title: str
    content: str
    date: str


@dataclasses.dataclass
class FakeAttendance:
    subject: str
    type: str
    date: str
    teacher: str


@dataclasses.dataclass
class FakeHomework:
    subject: str
    teacher: str
    description: str
    date: str
    href: str


@dataclasses.dataclass
class FakeHomeworkDetail:
    subject: str
    teacher: str
    description: str
    date_added: str
    date_due: str


@dataclasses.dataclass
class FakePeriod:
    subject: str
    teacher: str
    room: str
    start: str
    end: str


@dataclasses.dataclass
class FakeAnnouncement:
    title: str
    author: str
    date: str
    content: str


@dataclasses.dataclass
class FakeEvent:
    title: str
    date: str
    category: str


@dataclasses.dataclass
class FakeLesson:
    subject: str
    teacher: str
    topic: str
    date: str


@dataclasses.dataclass
class FakeStudentInfo:
    name: str
    class_name: str
    number: int
    tutor: str
    school: str
    lucky_number: int


# --- Helpers ---


def _mock_execute(return_value):
    """Create a patch for LibrusManager._execute that returns the given value."""
    return patch(
        "src.librus_client.LibrusManager._execute",
        new_callable=AsyncMock,
        return_value=return_value,
    )


# --- to_dict tests ---


class TestToDict:
    def test_dataclass(self):
        grade = FakeGrade("Math", "5", True, "2026-01-01", "/g/1", "test", 1, "cat", "Smith", 3)
        result = to_dict(grade)
        assert isinstance(result, dict)
        assert result["subject"] == "Math"
        assert result["grade"] == "5"

    def test_list_of_dataclasses(self):
        items = [FakeGpa(1, 4.5, "Math"), FakeGpa(2, 3.8, "English")]
        result = to_dict(items)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["gpa"] == 4.5

    def test_nested_dict(self):
        data = {"semester_1": [FakeGpa(1, 4.5, "Math")]}
        result = to_dict(data)
        assert result["semester_1"][0]["subject"] == "Math"

    def test_primitive(self):
        assert to_dict(42) == 42
        assert to_dict("hello") == "hello"
        assert to_dict(None) is None
        assert to_dict(True) is True

    def test_non_serializable_raises(self):
        with pytest.raises(AssertionError, match="non-serializable"):
            to_dict({1, 2, 3})

    def test_class_not_instance_raises(self):
        with pytest.raises(AssertionError, match="non-serializable"):
            to_dict(FakeGrade)


# --- Tool tests ---


class TestListStudents:
    @pytest.mark.asyncio
    async def test_returns_aliases(self):
        result = await list_students()
        assert result == ["test_student"]


class TestGetGrades:
    @pytest.mark.asyncio
    async def test_returns_numeric_gpa_descriptive(self):
        grades_data = (
            [
                defaultdict(
                    list,
                    {
                        "Math": [
                            FakeGrade(
                                "Math",
                                "5",
                                True,
                                "2026-01-01",
                                "/g/1",
                                "test",
                                1,
                                "cat",
                                "Smith",
                                3,
                            )
                        ]
                    },
                )
            ],
            defaultdict(list, {"Math": [FakeGpa(1, 4.5, "Math")]}),
            [],
        )
        with _mock_execute(grades_data):
            result = await get_grades("test_student")
        assert "numeric" in result
        assert "gpa" in result
        assert "descriptive" in result

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(ValueError, match="student_alias"):
            await get_grades("")

    @pytest.mark.asyncio
    async def test_invalid_sort_by_raises(self):
        with pytest.raises(ValueError, match="sort_by"):
            await get_grades("test_student", "newest")

    @pytest.mark.asyncio
    async def test_non_tuple_result_raises(self):
        with _mock_execute(["not", "a", "tuple"]):
            with pytest.raises(AssertionError, match="must return a tuple"):
                await get_grades("test_student")


class TestGetMessages:
    @pytest.mark.asyncio
    async def test_returns_received(self):
        messages = [FakeMessage("Teacher", "Test title", "2026-01-01", "/m/1")]
        mock = AsyncMock()
        mock.side_effect = [0, messages]  # max_page, then messages
        with patch("src.librus_client.LibrusManager._execute", mock):
            result = await get_messages("test_student")
        assert result["folder"] == "received"
        assert len(result["messages"]) == 1

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(ValueError, match="student_alias"):
            await get_messages("")


class TestGetMessageContent:
    @pytest.mark.asyncio
    async def test_returns_full_metadata(self):
        msg_data = FakeMessageData("Teacher", "Trip", "Hello parent", "2026-01-01")
        with _mock_execute(msg_data):
            result = await get_message_content("test_student", "123")
        assert result == {
            "author": "Teacher",
            "title": "Trip",
            "date": "2026-01-01",
            "content": "Hello parent",
        }

    @pytest.mark.asyncio
    async def test_empty_message_id_raises(self):
        with pytest.raises(ValueError, match="message_id"):
            await get_message_content("test_student", "")

    @pytest.mark.asyncio
    async def test_non_numeric_message_id_raises(self):
        with pytest.raises(ValueError, match="message_id"):
            await get_message_content("test_student", "/m/1")

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(ValueError, match="student_alias"):
            await get_message_content("", "123")


class TestGetAttendance:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        attendance = [FakeAttendance("Math", "present", "2026-01-01", "Smith")]
        with _mock_execute(attendance):
            result = await get_attendance("test_student")
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(ValueError, match="student_alias"):
            await get_attendance("")

    @pytest.mark.asyncio
    async def test_invalid_sort_by_raises(self):
        with pytest.raises(ValueError, match="sort_by"):
            await get_attendance("test_student", "oldest")


class TestGetSubjectFrequency:
    @pytest.mark.asyncio
    async def test_returns_dict(self):
        freq = {"Math": 95.0, "English": 88.5}
        with _mock_execute(freq):
            result = await get_subject_frequency("test_student")
        assert result["Math"] == 95.0
        assert result["English"] == 88.5

    @pytest.mark.asyncio
    async def test_with_date_range(self):
        freq = {"Math": 100.0}
        with _mock_execute(freq):
            result = await get_subject_frequency("test_student", "2026-01-01", "2026-03-01")
        assert result["Math"] == 100.0

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(ValueError, match="student_alias"):
            await get_subject_frequency("")


class TestGetHomework:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        hw = [FakeHomework("Math", "Smith", "Solve page 5", "2026-01-15", "/hw/1")]
        with _mock_execute(hw):
            result = await get_homework("test_student")
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(ValueError, match="student_alias"):
            await get_homework("")

    @pytest.mark.asyncio
    async def test_reversed_date_range_raises(self):
        with pytest.raises(ValueError, match="after"):
            await get_homework("test_student", "2026-02-01", "2026-01-01")

    @pytest.mark.asyncio
    async def test_single_date_raises(self):
        with pytest.raises(ValueError, match="together"):
            await get_homework("test_student", "2026-01-01", None)

    @pytest.mark.asyncio
    async def test_oversized_range_raises(self):
        with pytest.raises(ValueError, match="range exceeds"):
            await get_homework("test_student", "2024-01-01", "2026-01-01")


class TestGetHomeworkDetail:
    @pytest.mark.asyncio
    async def test_returns_detail(self):
        detail = FakeHomeworkDetail("Math", "Smith", "Full description", "2026-01-01", "2026-01-15")
        with _mock_execute(detail):
            result = await get_homework_detail("test_student", "1")
        assert result["subject"] == "Math"
        assert result["description"] == "Full description"

    @pytest.mark.asyncio
    async def test_empty_detail_url_raises(self):
        with pytest.raises(ValueError, match="detail_url"):
            await get_homework_detail("test_student", "")

    @pytest.mark.asyncio
    async def test_absolute_detail_url_raises(self):
        with pytest.raises(ValueError, match="numeric ID"):
            await get_homework_detail("test_student", "https://evil.example/hw/1")

    @pytest.mark.asyncio
    async def test_path_traversal_detail_url_raises(self):
        with pytest.raises(ValueError, match="numeric ID"):
            await get_homework_detail("test_student", "../../../../wiadomosci/5")

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(ValueError, match="student_alias"):
            await get_homework_detail("", "1")


class TestGetSchedule:
    @pytest.mark.asyncio
    async def test_returns_dict(self):
        schedule = {1: [FakeEvent("Test", "2026-01-15", "exam")]}
        with _mock_execute(schedule):
            result = await get_schedule("test_student", "2026", "1")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_invalid_month_raises(self):
        with pytest.raises(ValueError, match="month must be 1-12"):
            await get_schedule("test_student", "2026", "abc")

    @pytest.mark.asyncio
    async def test_invalid_year_raises(self):
        with pytest.raises(ValueError, match="year must be"):
            await get_schedule("test_student", "abc", "1")


class TestGetTimetable:
    @pytest.mark.asyncio
    async def test_returns_timetable(self):
        timetable = [[FakePeriod("Math", "Smith", "101", "08:00", "08:45")]]
        with _mock_execute(timetable):
            result = await get_timetable("test_student")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(ValueError, match="student_alias"):
            await get_timetable("")

    @pytest.mark.asyncio
    async def test_non_monday_raises(self):
        # 2026-07-14 is a Tuesday.
        with pytest.raises(ValueError, match="not a Monday"):
            await get_timetable("test_student", "2026-07-14")

    @pytest.mark.asyncio
    async def test_explicit_monday_accepted(self):
        timetable = [[FakePeriod("Math", "Smith", "101", "08:00", "08:45")]]
        with _mock_execute(timetable):
            result = await get_timetable("test_student", "2026-07-13")
        assert isinstance(result, list)


class TestGetAnnouncements:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        announcements = [FakeAnnouncement("School trip", "Director", "2026-01-01", "Details...")]
        with _mock_execute(announcements):
            result = await get_announcements("test_student")
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(ValueError, match="student_alias"):
            await get_announcements("")


class TestGetCompletedLessons:
    @pytest.mark.asyncio
    async def test_returns_list_with_pagination(self):
        """Completed lessons paginates through all pages."""
        page_0 = [FakeLesson("Math", "Smith", "Algebra basics", "2026-01-15")]
        page_1 = [FakeLesson("English", "Jones", "Grammar", "2026-01-16")]

        mock = AsyncMock()
        # First call: get_max_page_number returns 1 (2 pages: 0 and 1)
        # Second call: get_completed page 0
        # Third call: get_completed page 1
        mock.side_effect = [1, page_0, page_1]

        with patch("src.librus_client.LibrusManager._execute", mock):
            result = await get_completed_lessons("test_student", "2026-01-01", "2026-01-31")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["subject"] == "Math"
        assert result[1]["subject"] == "English"

    @pytest.mark.asyncio
    async def test_single_page(self):
        """When max_page is 0, only page 0 is fetched."""
        page_0 = [FakeLesson("Math", "Smith", "Lesson 1", "2026-01-15")]

        mock = AsyncMock()
        mock.side_effect = [0, page_0]

        with patch("src.librus_client.LibrusManager._execute", mock):
            result = await get_completed_lessons("test_student", "2026-01-01", "2026-01-31")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_date_from_raises(self):
        with pytest.raises(ValueError, match="date_from"):
            await get_completed_lessons("test_student", "", "2026-01-31")

    @pytest.mark.asyncio
    async def test_empty_date_to_raises(self):
        with pytest.raises(ValueError, match="date_to"):
            await get_completed_lessons("test_student", "2026-01-01", "")

    @pytest.mark.asyncio
    async def test_malformed_date_raises(self):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            await get_completed_lessons("test_student", "31.01.2026", "2026-01-31")

    @pytest.mark.asyncio
    async def test_reversed_range_raises(self):
        with pytest.raises(ValueError, match="after"):
            await get_completed_lessons("test_student", "2026-01-31", "2026-01-01")

    @pytest.mark.asyncio
    async def test_oversized_range_raises(self):
        with pytest.raises(ValueError, match="range exceeds"):
            await get_completed_lessons("test_student", "2024-01-01", "2026-01-31")

    @pytest.mark.asyncio
    async def test_implausible_page_count_raises(self):
        mock = AsyncMock()
        mock.side_effect = [500]  # remote-controlled max_page
        with patch("src.librus_client.LibrusManager._execute", mock):
            with pytest.raises(ValueError, match="narrow the date range"):
                await get_completed_lessons("test_student", "2026-01-01", "2026-01-31")

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(ValueError, match="student_alias"):
            await get_completed_lessons("", "2026-01-01", "2026-01-31")


class TestGetStudentInformation:
    @pytest.mark.asyncio
    async def test_returns_info(self):
        info = FakeStudentInfo("Jan Kowalski", "3a", 15, "Anna Nowak", "SP Rząska", 7)
        with _mock_execute(info):
            result = await get_student_information("test_student")
        assert result["name"] == "Jan Kowalski"
        assert result["class_name"] == "3a"
        assert result["lucky_number"] == 7

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(ValueError, match="student_alias"):
            await get_student_information("")


# --- Assertion coverage tests ---


class TestFetchAssertions:
    """Verify that LibrusManager.fetch_* assertions fire on malformed upstream data."""

    @pytest.mark.asyncio
    async def test_grades_rejects_non_tuple(self):
        with _mock_execute(["not", "a", "tuple"]):
            with pytest.raises(AssertionError, match="must return a tuple"):
                await get_grades("test_student")

    @pytest.mark.asyncio
    async def test_grades_rejects_wrong_length_tuple(self):
        with _mock_execute(([], [])):
            with pytest.raises(AssertionError, match="must return.*grades, gpa, descriptive"):
                await get_grades("test_student")

    @pytest.mark.asyncio
    async def test_messages_rejects_non_list(self):
        mock = AsyncMock()
        mock.side_effect = [0, "not a list"]  # valid max_page, malformed messages
        with patch("src.librus_client.LibrusManager._execute", mock):
            with pytest.raises(AssertionError, match="must return a list"):
                await get_messages("test_student")

    @pytest.mark.asyncio
    async def test_attendance_rejects_non_list(self):
        with _mock_execute({"wrong": "type"}):
            with pytest.raises(AssertionError, match="must return a list"):
                await get_attendance("test_student")

    @pytest.mark.asyncio
    async def test_homework_rejects_non_list(self):
        with _mock_execute(42):
            with pytest.raises(AssertionError, match="must return a list"):
                await get_homework("test_student")

    @pytest.mark.asyncio
    async def test_announcements_rejects_non_list(self):
        with _mock_execute("string"):
            with pytest.raises(AssertionError, match="must return a list"):
                await get_announcements("test_student")

    @pytest.mark.asyncio
    async def test_subject_frequency_rejects_non_dict(self):
        with _mock_execute([1, 2, 3]):
            with pytest.raises(AssertionError, match="must return a dict"):
                await get_subject_frequency("test_student")

    @pytest.mark.asyncio
    async def test_timetable_rejects_non_list(self):
        with _mock_execute("not a list"):
            with pytest.raises(AssertionError, match="must return a list"):
                await get_timetable("test_student")

    @pytest.mark.asyncio
    async def test_schedule_rejects_non_dict(self):
        with _mock_execute([1, 2]):
            with pytest.raises(AssertionError, match="must return a dict"):
                await get_schedule("test_student", "2026", "1")

    @pytest.mark.asyncio
    async def test_message_content_rejects_none(self):
        with _mock_execute(None):
            with pytest.raises(AssertionError, match="returned None"):
                await get_message_content("test_student", "123")

    @pytest.mark.asyncio
    async def test_student_info_rejects_none(self):
        with _mock_execute(None):
            with pytest.raises(AssertionError, match="returned None"):
                await get_student_information("test_student")

    @pytest.mark.asyncio
    async def test_homework_detail_rejects_none(self):
        with _mock_execute(None):
            with pytest.raises(AssertionError, match="returned None"):
                await get_homework_detail("test_student", "1")
