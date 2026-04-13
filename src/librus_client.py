import asyncio
from typing import Callable, Any
from datetime import datetime, timedelta
from librus_apix.client import Client, Token, new_client
from librus_apix.exceptions import AuthorizationError, TokenKeyError
from librus_apix.grades import get_grades
from librus_apix.messages import get_received, message_content
from librus_apix.attendance import get_attendance, get_subject_frequency
from librus_apix.homework import get_homework, homework_detail
from librus_apix.timetable import get_timetable
from librus_apix.announcements import get_announcements
from librus_apix.schedule import get_schedule
from librus_apix.completed_lessons import get_completed, get_max_page_number
from librus_apix.student_information import get_student_information
from src.config import load_config, AppConfig


class LibrusManager:
    _instances: dict[str, Client] = {}
    _tokens: dict[str, Token] = {}
    _config_cache: AppConfig | None = None

    @classmethod
    def _get_config(cls) -> AppConfig:
        """Load and cache the application config. Reads disk only once."""
        if cls._config_cache is None:
            cls._config_cache = load_config()
        return cls._config_cache

    @classmethod
    async def get_client(cls, alias: str) -> Client:
        assert alias, "Alias must not be empty"
        assert isinstance(alias, str), "Alias must be a string"

        if alias in cls._instances:
            return cls._instances[alias]

        config = cls._get_config()
        account = next((acc for acc in config.accounts if acc.alias == alias), None)

        if not account:
            raise ValueError(f"Account with alias '{alias}' not found in configuration.")

        client = new_client()
        try:
            token = await asyncio.to_thread(client.get_token, account.username, account.password)
        except Exception as e:
            raise ValueError(f"Failed to authenticate for '{alias}': {e}")

        assert token is not None, f"Authentication returned None token for '{alias}'"
        cls._instances[alias] = client
        cls._tokens[alias] = token

        return client

    @classmethod
    def _evict_client(cls, alias: str) -> None:
        """Remove cached client and token so the next call re-authenticates."""
        cls._instances.pop(alias, None)
        cls._tokens.pop(alias, None)

    @classmethod
    async def _execute(cls, alias: str, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Execute a blocking librus-apix call on a thread, with one retry on auth failure.

        The retry exists because Librus session tokens expire after ~30 minutes
        of inactivity. When that happens, the upstream library raises
        AuthorizationError or TokenKeyError. We evict the cached client and
        re-authenticate once. If the second attempt also fails, we let it propagate.
        """
        assert alias, "Alias must not be empty"
        client = await cls.get_client(alias)
        try:
            return await asyncio.to_thread(func, client, *args, **kwargs)
        except (AuthorizationError, TokenKeyError):
            # Token likely expired. Clear cache and re-authenticate once.
            cls._evict_client(alias)
            client = await cls.get_client(alias)
            return await asyncio.to_thread(func, client, *args, **kwargs)

    @classmethod
    def list_accounts(cls) -> list[str]:
        config = cls._get_config()
        assert len(config.accounts) > 0, "Config must contain at least one account"
        return [acc.alias for acc in config.accounts]

    # --- Data Retrieval Methods ---

    @classmethod
    async def fetch_grades(cls, alias: str) -> dict[str, Any]:
        assert alias, "Alias must not be empty"
        result = await cls._execute(alias, get_grades)
        assert isinstance(result, tuple), "get_grades must return a tuple"
        assert len(result) == 3, "get_grades must return (grades, gpa, descriptive)"
        grades, gpa, descriptive = result
        return {"numeric": grades, "gpa": gpa, "descriptive": descriptive}

    @classmethod
    async def fetch_messages(cls, alias: str) -> dict[str, Any]:
        assert alias, "Alias must not be empty"
        received = await cls._execute(alias, get_received, 1)
        assert isinstance(received, list), "get_received must return a list"
        return {"received": received}

    @classmethod
    async def fetch_message_content(cls, alias: str, message_id: str) -> str:
        """Fetch the body of a specific message by its ID (from the 'href' field)."""
        assert alias, "Alias must not be empty"
        assert message_id, "Message ID must not be empty"
        message_data = await cls._execute(alias, message_content, message_id)
        assert message_data is not None, "message_content returned None"
        return message_data.content

    @classmethod
    async def fetch_attendance(cls, alias: str) -> list[Any]:
        assert alias, "Alias must not be empty"
        attendance = await cls._execute(alias, get_attendance)
        assert isinstance(attendance, list), "get_attendance must return a list"
        return attendance

    @classmethod
    async def fetch_subject_frequency(
        cls, alias: str, start: str | None = None, end: str | None = None
    ) -> dict[str, Any]:
        """Fetch per-subject attendance frequency, optionally filtered by date range."""
        assert alias, "Alias must not be empty"
        kwargs: dict[str, Any] = {}
        if start:
            assert len(start) == 10, f"start must be YYYY-MM-DD, got: '{start}'"
            kwargs["start"] = datetime.strptime(start, "%Y-%m-%d")
        if end:
            assert len(end) == 10, f"end must be YYYY-MM-DD, got: '{end}'"
            kwargs["end"] = datetime.strptime(end, "%Y-%m-%d")
        frequency = await cls._execute(alias, get_subject_frequency, **kwargs)
        assert isinstance(frequency, dict), "get_subject_frequency must return a dict"
        return dict(frequency)

    @classmethod
    async def fetch_homework(cls, alias: str) -> list[Any]:
        assert alias, "Alias must not be empty"
        today = datetime.now()
        start = today.strftime("%Y-%m-%d")
        end = (today + timedelta(days=14)).strftime("%Y-%m-%d")
        homework = await cls._execute(alias, get_homework, start, end)
        assert isinstance(homework, list), "get_homework must return a list"
        return homework

    @classmethod
    async def fetch_homework_detail(cls, alias: str, detail_url: str) -> Any:
        """Fetch full details of a specific homework assignment."""
        assert alias, "Alias must not be empty"
        assert detail_url, "detail_url must not be empty"
        detail = await cls._execute(alias, homework_detail, detail_url)
        assert detail is not None, "homework_detail returned None"
        return detail

    @classmethod
    async def fetch_schedule(cls, alias: str, month: str, year: str) -> dict[int, Any]:
        assert alias, "Alias must not be empty"
        assert month.isdigit(), "Month must be a numeric string"
        month_int = int(month)
        assert 1 <= month_int <= 12, "Month must be between 1 and 12"
        assert year.isdigit(), "Year must be a numeric string"
        assert int(year) > 2000, "Year must be > 2000"

        schedule = await cls._execute(alias, get_schedule, month, year, include_empty=False)
        assert isinstance(schedule, dict), "get_schedule must return a dict"
        return dict(schedule)

    @classmethod
    async def fetch_timetable(cls, alias: str) -> list[Any]:
        assert alias, "Alias must not be empty"
        today = datetime.now()
        # Find Monday of the current week.
        monday = today - timedelta(days=today.weekday())
        timetable = await cls._execute(alias, get_timetable, monday)
        assert isinstance(timetable, list), "get_timetable must return a list"
        return timetable

    @classmethod
    async def fetch_announcements(cls, alias: str) -> list[Any]:
        assert alias, "Alias must not be empty"
        announcements = await cls._execute(alias, get_announcements)
        assert isinstance(announcements, list), "get_announcements must return a list"
        return announcements

    @classmethod
    async def fetch_completed_lessons(cls, alias: str, date_from: str, date_to: str) -> list[Any]:
        """Fetch completed lessons for a date range, iterating all pages."""
        assert alias, "Alias must not be empty"
        assert date_from, "date_from must not be empty"
        assert date_to, "date_to must not be empty"

        max_page = await cls._execute(alias, get_max_page_number, date_from, date_to)
        assert isinstance(max_page, int), "get_max_page_number must return an int"
        assert max_page <= 100, f"Unexpectedly high page count: {max_page}"

        all_lessons: list[Any] = []
        for page in range(max_page + 1):
            lessons = await cls._execute(alias, get_completed, date_from, date_to, page)
            assert isinstance(lessons, list), "get_completed must return a list"
            all_lessons.extend(lessons)
        return all_lessons

    @classmethod
    async def fetch_student_information(cls, alias: str) -> Any:
        """Fetch student profile information (name, class, tutor, school, lucky number)."""
        assert alias, "Alias must not be empty"
        info = await cls._execute(alias, get_student_information)
        assert info is not None, "get_student_information returned None"
        return info
