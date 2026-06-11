import asyncio
from typing import Callable, Any
from datetime import datetime, timedelta
from librus_apix.client import Client, Token, new_client
from librus_apix.exceptions import AuthorizationError, TokenKeyError
from librus_apix.grades import get_grades
from librus_apix.messages import (
    get_max_page_number as get_message_max_page,
    get_received,
    get_recipients,
    get_sent,
    message_content,
    recipient_groups,
    send_message,
)
from librus_apix.attendance import get_attendance, get_subject_frequency
from librus_apix.homework import get_homework, homework_detail
from librus_apix.timetable import get_timetable
from librus_apix.announcements import get_announcements
from librus_apix.notifications import NotificationIds, get_new_notification_data
from librus_apix.schedule import get_recently_added_schedule, get_schedule
from librus_apix.completed_lessons import get_completed, get_max_page_number
from librus_apix.student_information import get_student_information
from src import scraping
from src.config import load_config, AppConfig
from src.notification_state import (
    load_notification_ids,
    resolve_state_dir,
    save_notification_ids,
)

MESSAGE_FOLDERS = ("received", "sent")


class LibrusManager:
    _instances: dict[str, Client] = {}
    _tokens: dict[str, Token] = {}
    _config_cache: AppConfig | None = None
    _notification_locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def _notification_lock(cls, alias: str) -> asyncio.Lock:
        """One lock per alias serializes load -> diff -> save of notification
        state. Without it, two concurrent calls would both read the same seen
        IDs and the second save would discard the first call's updates, so its
        notifications would be reported again on the next call."""
        assert alias, "Alias must not be empty"
        if alias not in cls._notification_locks:
            cls._notification_locks[alias] = asyncio.Lock()
        return cls._notification_locks[alias]

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
    async def fetch_messages(
        cls, alias: str, page: int = 0, folder: str = "received"
    ) -> dict[str, Any]:
        """Fetch one page of messages from the received or sent folder.

        Librus pages are 0-based: page 0 holds the newest messages and
        max_page is the last valid index (verified live; out-of-range pages
        silently clamp to the last page server-side).
        """
        assert alias, "Alias must not be empty"
        assert isinstance(page, int), "page must be an int"
        assert 0 <= page <= 1000, f"page out of range: {page}"
        if folder == "received":
            max_page = await cls._execute(alias, get_message_max_page)
            assert isinstance(max_page, int), "get_max_page_number must return an int"
            assert page <= max_page, f"page {page} exceeds max_page {max_page}"
            messages = await cls._execute(alias, get_received, page)
        elif folder == "sent":
            # Librus exposes no page counter for the sent folder.
            max_page = None
            messages = await cls._execute(alias, get_sent, page)
        else:
            assert False, f"folder must be one of {MESSAGE_FOLDERS}, got: '{folder}'"
        assert isinstance(messages, list), "message fetch must return a list"
        return {"messages": messages, "folder": folder, "page": page, "max_page": max_page}

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

    @classmethod
    async def fetch_recent_schedule_events(cls, alias: str) -> list[Any]:
        """Fetch schedule events added since the last Librus login."""
        assert alias, "Alias must not be empty"
        events = await cls._execute(alias, get_recently_added_schedule)
        assert isinstance(events, list), "get_recently_added_schedule must return a list"
        return events

    @classmethod
    async def fetch_new_notifications(cls, alias: str) -> dict[str, Any]:
        """Diff current Librus data against persisted seen-IDs and return what is new.

        First run for an alias has no state file: diff against empty IDs, which
        returns the items since the last Librus login as baseline. We deliberately
        avoid get_initial_notification_data — it scrapes /uczen/index, which
        returns 403 for parent (rodzic) accounts.
        """
        assert alias, "Alias must not be empty"
        config = cls._get_config()
        state_dir = resolve_state_dir(config.state_dir)
        async with cls._notification_lock(alias):
            seen_ids = load_notification_ids(state_dir, alias)
            first_run = seen_ids is None
            if seen_ids is None:
                seen_ids = NotificationIds([], [], [], [], [], [])
            result = await cls._execute(alias, get_new_notification_data, seen_ids)
            assert isinstance(result, tuple), "notification fetch must return a tuple"
            assert len(result) == 2, "notification fetch must return (data, ids)"
            data, updated_ids = result
            save_notification_ids(state_dir, alias, updated_ids)
        return {"first_run": first_run, "new": data}

    @classmethod
    async def fetch_recipient_groups(cls, alias: str) -> list[str]:
        """Fetch recipient group identifiers available for sending messages."""
        assert alias, "Alias must not be empty"
        groups = await cls._execute(alias, recipient_groups)
        assert isinstance(groups, list), "recipient_groups must return a list"
        return groups

    @classmethod
    async def fetch_recipients(cls, alias: str, group: str) -> dict[str, str]:
        """Fetch recipients (name -> id) belonging to a recipient group."""
        assert alias, "Alias must not be empty"
        assert group, "group must not be empty"
        recipients = await cls._execute(alias, get_recipients, group)
        assert isinstance(recipients, dict), "get_recipients must return a dict"
        return recipients

    @classmethod
    async def send_message_to(
        cls, alias: str, title: str, content: str, recipient_ids: list[str]
    ) -> dict[str, Any]:
        """Send a message via the school messaging system. Write action."""
        assert alias, "Alias must not be empty"
        assert title, "title must not be empty"
        assert content, "content must not be empty"
        assert isinstance(recipient_ids, list), "recipient_ids must be a list"
        assert len(recipient_ids) > 0, "recipient_ids must not be empty"
        assert len(recipient_ids) <= 50, f"implausible recipient count: {len(recipient_ids)}"
        result = await cls._execute(alias, send_message, title, content, recipient_ids)
        assert isinstance(result, tuple), "send_message must return a tuple"
        assert len(result) == 2, "send_message must return (success, message)"
        success, status_message = result
        return {"success": bool(success), "result": status_message}

    @classmethod
    async def fetch_message_attachments(cls, alias: str, message_id: str) -> list[Any]:
        """List attachments of a message (own scraping; librus-apix lacks this)."""
        assert alias, "Alias must not be empty"
        assert message_id, "message_id must not be empty"
        attachments = await cls._execute(alias, scraping.get_attachments, message_id)
        assert isinstance(attachments, list), "get_attachments must return a list"
        return attachments

    @classmethod
    async def download_message_attachment(
        cls, alias: str, message_id: str, file_id: str
    ) -> dict[str, Any]:
        """Download one message attachment to the configured download dir."""
        assert alias, "Alias must not be empty"
        assert message_id, "message_id must not be empty"
        assert file_id, "file_id must not be empty"
        config = cls._get_config()
        download_dir = scraping.resolve_download_dir(config.download_dir)
        info = await cls._execute(
            alias, scraping.download_attachment, message_id, file_id, download_dir
        )
        assert isinstance(info, dict), "download_attachment must return a dict"
        return info

    @classmethod
    async def fetch_final_grades(cls, alias: str) -> list[Any]:
        """Fetch end-of-year grade columns (midterm, predicted annual, annual).

        Own scraping: librus-apix parses only current grades and skips the
        (I)/(R)/R summary columns of the grades table.
        """
        assert alias, "Alias must not be empty"
        grades = await cls._execute(alias, scraping.get_final_grades)
        assert isinstance(grades, list), "get_final_grades must return a list"
        return grades

    @classmethod
    async def fetch_behaviour_notes(cls, alias: str) -> list[Any]:
        """Fetch behaviour notes (uwagi) — own scraping; librus-apix lacks this."""
        assert alias, "Alias must not be empty"
        notes = await cls._execute(alias, scraping.get_behaviour_notes)
        assert isinstance(notes, list), "get_behaviour_notes must return a list"
        return notes
