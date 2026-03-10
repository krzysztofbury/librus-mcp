import asyncio
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
from librus_apix.client import Client, Token, new_client
from librus_apix.grades import get_grades
from librus_apix.messages import get_received, message_content
from librus_apix.attendance import get_attendance
from librus_apix.homework import get_homework
from librus_apix.timetable import get_timetable
from librus_apix.announcements import get_announcements
from librus_apix.schedule import get_schedule
from src.config import load_config, AppConfig

# Upper bound for retry attempts on authentication failures.
MAX_AUTH_RETRIES = 1


class LibrusManager:
    _instances: Dict[str, Client] = {}
    _tokens: Dict[str, Token] = {}
    _config_cache: Optional[AppConfig] = None

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
    async def _execute(cls, alias: str, func, *args, **kwargs) -> Any:
        """Execute a librus-apix call with automatic re-auth on token expiry."""
        assert alias, "Alias must not be empty"
        client = await cls.get_client(alias)
        try:
            return await asyncio.to_thread(func, client, *args, **kwargs)
        except Exception as error:
            error_message = str(error).lower()
            is_auth_error = any(
                keyword in error_message
                for keyword in ("token", "auth", "session", "login", "expired")
            )
            if is_auth_error:
                # Token likely expired. Clear cache and re-authenticate once.
                cls._evict_client(alias)
                client = await cls.get_client(alias)
                return await asyncio.to_thread(func, client, *args, **kwargs)
            raise

    @classmethod
    def list_accounts(cls) -> list[str]:
        config = cls._get_config()
        return [acc.alias for acc in config.accounts]

    # --- Data Retrieval Methods ---

    @classmethod
    async def fetch_grades(cls, alias: str) -> list[Any]:
        assert alias, "Alias must not be empty"
        result = await cls._execute(alias, get_grades)
        assert isinstance(result, tuple), "get_grades must return a tuple"
        assert len(result) == 3, "get_grades must return (grades, gpa, descriptive)"
        grades, _gpa, _descriptive = result
        return grades

    @classmethod
    async def fetch_messages(cls, alias: str) -> Dict[str, Any]:
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
    async def fetch_homework(cls, alias: str) -> list[Any]:
        assert alias, "Alias must not be empty"
        today = datetime.now()
        start = today.strftime("%Y-%m-%d")
        end = (today + timedelta(days=14)).strftime("%Y-%m-%d")
        homework = await cls._execute(alias, get_homework, start, end)
        assert isinstance(homework, list), "get_homework must return a list"
        return homework

    @classmethod
    async def fetch_schedule(cls, alias: str, month: str, year: str) -> Dict[int, Any]:
        assert alias, "Alias must not be empty"
        assert month.isdigit(), "Month must be a numeric string"
        month_int = int(month)
        assert 1 <= month_int <= 12, "Month must be between 1 and 12"
        assert year.isdigit(), "Year must be a numeric string"
        assert int(year) > 2000, "Year must be > 2000"

        schedule = await cls._execute(alias, get_schedule, month, year, include_empty=False)
        return dict(schedule)

    @classmethod
    async def fetch_timetable(cls, alias: str) -> Dict[str, Any]:
        assert alias, "Alias must not be empty"
        today = datetime.now()
        # Find Monday of the current week.
        monday = today - timedelta(days=today.weekday())
        timetable = await cls._execute(alias, get_timetable, monday)
        return timetable

    @classmethod
    async def fetch_announcements(cls, alias: str) -> list[Any]:
        assert alias, "Alias must not be empty"
        announcements = await cls._execute(alias, get_announcements)
        assert isinstance(announcements, list), "get_announcements must return a list"
        return announcements
