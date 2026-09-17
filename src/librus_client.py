import asyncio
import re
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import local
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from librus_apix.announcements import get_announcements
from librus_apix.attendance import (
    get_attendance,
    get_attendance_frequency,
)
from librus_apix.attendance import (
    get_detail as get_attendance_detail,
)
from librus_apix.client import Client, Token, new_client
from librus_apix.completed_lessons import get_completed
from librus_apix.exceptions import (
    AuthorizationError,
    MaintananceError,
    ParseError,
    TokenError,
    TokenKeyError,
)
from librus_apix.grades import get_grades
from librus_apix.homework import get_homework, homework_detail
from librus_apix.messages import (
    get_max_page_number as get_message_max_page,
)
from librus_apix.messages import (
    get_received,
    get_recipients,
    get_sent,
    message_content,
    recipient_groups,
    send_message,
)
from librus_apix.notifications import NotificationIds
from librus_apix.schedule import RecentEvent, get_schedule, schedule_detail
from librus_apix.student_information import get_student_information
from librus_apix.timetable import get_timetable
from requests import Session
from requests.cookies import RequestsCookieJar
from requests.exceptions import JSONDecodeError as RequestsJSONDecodeError

from src import librus_optimizations, scraping
from src.config import AccountConfig, AppConfig, load_config, validate_alias
from src.notification_state import (
    clear_pending_schedule_events,
    load_notification_ids,
    load_pending_schedule_events,
    release_notification_state_lock,
    save_notification_ids,
    save_pending_schedule_events,
    try_acquire_notification_state_lock,
)
from src.response_limits import (
    MAX_RESPONSE_BODY_BYTES,
    RESPONSE_READ_CHUNK_BYTES,
    ResponseTooLargeError,
)

MESSAGE_FOLDERS = ("received", "sent")
SORT_FILTERS = ("all", "week", "last_login")
MESSAGES_PER_PAGE = 50
MAX_MESSAGE_PAGE = 1000
# Bounded "fetch everything": 40 pages x 50 messages = 2000 messages. Larger
# mailboxes return the newest 2000 with truncated=True instead of an
# unbounded loop against a scraped endpoint.
MAX_ALL_MESSAGE_PAGES = 40
MAX_ALL_MESSAGE_ITEMS = MAX_ALL_MESSAGE_PAGES * MESSAGES_PER_PAGE
MAX_HOMEWORK_RANGE_DAYS = 370
MAX_COMPLETED_LESSONS_RANGE_DAYS = 370
MAX_COMPLETED_LESSONS_PAGES = 100
MAX_COMPLETED_LESSONS_ITEMS = 10_000
MAX_SEND_TITLE_LENGTH = 200
MAX_SEND_CONTENT_LENGTH = 15_000
MAX_SEND_RECIPIENTS = 50
MAX_RECIPIENT_ID_LENGTH = 20
MAX_SEND_PAYLOAD_BYTES = 64 * 1024
DATE_FORMAT = "%Y-%m-%d"
SCHOOL_TIME_ZONE = ZoneInfo("Europe/Warsaw")
# Upstream reports expired sessions in three ways: AuthorizationError and
# TokenKeyError from the auth layer, TokenError when a page renders the
# "Brak dostępu" (no access) message.
AUTH_ERRORS = (AuthorizationError, TokenError, TokenKeyError)
# After a failed login, further login attempts for that account are refused
# for this long. Librus throttles the login endpoint per account; a caller
# retrying a failing tool in a loop would otherwise deepen the throttle
# (or, with bad credentials, risk a real lockout).
AUTH_COOLDOWN_SECONDS = 60.0
# A second operation-level auth failure after a fresh login indicates endpoint
# denial rather than ordinary session expiry. Bound repeated login pressure for
# that alias and operation while leaving unrelated tools available.
OPERATION_AUTH_COOLDOWN_SECONDS = 60.0
# One denied endpoint does not disable healthy tools. Repeated denials across
# distinct endpoints indicate an account-wide problem and cap the total login
# attempts in one cooldown window.
MAX_PERSISTENT_DENIALS_PER_ALIAS = 3
LOGIN_AUTHORIZATION_URL_SUFFIX = "/OAuth/Authorization?client_id=46"
# Upstream librus-apix does not pass a timeout to requests.Session. Replace
# each client session so login and every synchronous upstream call have one.
UPSTREAM_REQUEST_TIMEOUT_SECONDS = 30.0
MAX_UPSTREAM_RESPONSE_BYTES = MAX_RESPONSE_BODY_BYTES
MAX_UPSTREAM_RESPONSE_CHAIN_BYTES = MAX_RESPONSE_BODY_BYTES
MAX_UPSTREAM_REDIRECTS = 10
# This also bounds non-requests work in librus-apix, such as HTML parsing and
# its aiohttp attendance helper. A timed-out client is retired before the
# per-alias lock is released, so its lingering worker can never share a
# requests.Session with a subsequent call.
UPSTREAM_OPERATION_TIMEOUT_SECONDS = 120.0
NOTIFICATION_LOCK_RETRY_SECONDS = 0.05
NOTIFICATION_LOCK_MAX_ATTEMPTS = 2400

SCHEDULE_HREF_PATTERN = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_/-]+$")


def _require_alias(alias: Any) -> str:
    try:
        return validate_alias(alias)
    except ValueError as error:
        raise ValueError(str(error).replace("account alias", "student_alias")) from None


def _require_non_empty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_message_id(value: Any, name: str = "message_id") -> str:
    _require_non_empty(value, name)
    if not value.isdigit():
        raise ValueError(f"{name} must be a numeric ID, got: '{value}'")
    return value


def _require_sort_by(value: Any) -> str:
    if value not in SORT_FILTERS:
        raise ValueError(f"sort_by must be one of {SORT_FILTERS}, got: '{value}'")
    return value


def _parse_date(value: Any, name: str) -> date:
    _require_non_empty(value, name)
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except ValueError:
        raise ValueError(f"{name} must be a YYYY-MM-DD date, got: '{value}'")


class LibrusTimeoutSession(Session):
    """A persistent requests session that supplies the timeout librus-apix omits."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.max_redirects = MAX_UPSTREAM_REDIRECTS
        self._response_budget = local()
        self._login_throttle_confirmed = False

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", UPSTREAM_REQUEST_TIMEOUT_SECONDS)
        # Session.send() applies the cap to the initial response and every
        # redirect hop before requests can buffer an intermediate body.
        kwargs["stream"] = True
        response = super().request(method, url, **kwargs)
        if method.upper() == "POST" and url.endswith(LOGIN_AUTHORIZATION_URL_SUFFIX):
            self._login_throttle_confirmed = (
                response.status_code == 429 or "Retry-After" in response.headers
            )
        return response

    def send(self, request: Any, **kwargs: Any) -> Any:
        allow_redirects = kwargs.pop("allow_redirects", True)
        kwargs["stream"] = True
        owns_response_budget = not hasattr(self._response_budget, "remaining_bytes")
        if owns_response_budget:
            self._response_budget.remaining_bytes = MAX_UPSTREAM_RESPONSE_CHAIN_BYTES
        try:
            response = super().send(request, allow_redirects=False, **kwargs)
            try:
                if request.url.endswith(LOGIN_AUTHORIZATION_URL_SUFFIX) and (
                    response.status_code == 429 or "Retry-After" in response.headers
                ):
                    self._login_throttle_confirmed = True
                declared_length = response.headers.get("Content-Length")
                if declared_length is not None:
                    declared_length = int(declared_length)
                    if (
                        declared_length > MAX_UPSTREAM_RESPONSE_BYTES
                        or declared_length > self._response_budget.remaining_bytes
                    ):
                        raise ResponseTooLargeError(
                            "Librus response body is too large "
                            f"(maximum {MAX_UPSTREAM_RESPONSE_BYTES} bytes)"
                        )
                body = bytearray()
                for chunk in response.iter_content(chunk_size=RESPONSE_READ_CHUNK_BYTES):
                    body.extend(chunk)
                    self._response_budget.remaining_bytes -= len(chunk)
                    if (
                        len(body) > MAX_UPSTREAM_RESPONSE_BYTES
                        or self._response_budget.remaining_bytes < 0
                    ):
                        raise ResponseTooLargeError(
                            "Librus response body is too large "
                            f"(maximum {MAX_UPSTREAM_RESPONSE_BYTES} bytes)"
                        )
                response._content = bytes(body)
                response._content_consumed = True
            except Exception:
                response.close()
                raise
            if allow_redirects:
                history = list(self.resolve_redirects(response, request, **kwargs))
                if history:
                    history.insert(0, response)
                    response = history.pop()
                    response.history = history
            return response
        finally:
            if owns_response_budget:
                del self._response_budget.remaining_bytes

    def __exit__(self, *args: object) -> None:
        # librus-apix wraps every request in `with client._session`, which
        # otherwise closes the adapters and discards the TCP/TLS pool.
        return None


class LibrusManager:
    _instances: ClassVar[dict[str, Client]] = {}
    _tokens: ClassVar[dict[str, Token]] = {}
    _config_cache: ClassVar[AppConfig | None] = None
    _notification_locks: ClassVar[dict[str, asyncio.Lock]] = {}
    _client_locks: ClassVar[dict[str, asyncio.Lock]] = {}
    # alias -> (monotonic deadline, failure reason). Bounded: only configured
    # aliases reach the code that writes here.
    _auth_cooldowns: ClassVar[dict[str, tuple[float, str]]] = {}
    # (alias, module-qualified operation) -> (monotonic deadline, reason).
    # Both key dimensions come from configured accounts and internal call sites.
    _operation_auth_cooldowns: ClassVar[dict[tuple[str, str], tuple[float, str]]] = {}
    # A Python thread cannot be stopped. Timed-out workers keep the alias
    # unavailable until they finish, preventing concurrent reuse of its session.
    _timed_out_workers: ClassVar[dict[str, asyncio.Task[Any]]] = {}

    @classmethod
    def _require_account(cls, alias: str) -> AccountConfig:
        """Validate the alias against configured accounts before any lock or
        client state is created for it, so unknown aliases cannot grow the
        lock maps and every caller fails with the same actionable error."""
        _require_alias(alias)
        config = cls._get_config()
        account = next((acc for acc in config.accounts if acc.alias == alias), None)
        if account is None:
            known = ", ".join(f"'{acc.alias}'" for acc in config.accounts)
            raise ValueError(f"Account with alias '{alias}' not found. Configured: {known}.")
        return account

    @classmethod
    def _notification_lock(cls, alias: str) -> asyncio.Lock:
        """One lock per alias serializes load -> diff -> save of notification
        state. Without it, two concurrent calls would both read the same seen
        IDs and the second save would discard the first call's updates, so its
        notifications would be reported again on the next call."""
        assert alias in {acc.alias for acc in cls._get_config().accounts}, (
            "callers must validate the alias before acquiring its lock"
        )
        if alias not in cls._notification_locks:
            cls._notification_locks[alias] = asyncio.Lock()
        return cls._notification_locks[alias]

    @classmethod
    def _client_lock(cls, alias: str) -> asyncio.Lock:
        """One lock per alias serializes upstream operations for that account.
        An operation may use isolated internal workers, but other operations
        cannot overlap the shared requests session or cookie jar."""
        assert alias in {acc.alias for acc in cls._get_config().accounts}, (
            "callers must validate the alias before acquiring its lock"
        )
        if alias not in cls._client_locks:
            cls._client_locks[alias] = asyncio.Lock()
        return cls._client_locks[alias]

    @classmethod
    def _get_config(cls) -> AppConfig:
        """Load and cache the application config. Reads disk only once."""
        if cls._config_cache is None:
            cls._config_cache = load_config()
        return cls._config_cache

    @classmethod
    async def get_client(cls, alias: str) -> Client:
        """Return the cached client for an alias, authenticating on first use.

        Not safe to call concurrently for one alias outside _execute: the
        per-alias client lock lives there, and this method mutates the shared
        instance/token caches."""
        account = cls._require_account(alias)
        cls._raise_if_worker_is_running(alias)

        if alias in cls._instances:
            return cls._instances[alias]

        cls._check_auth_cooldown(alias)

        client = new_client()
        client._session.close()
        client._session = LibrusTimeoutSession()
        # Upstream librus-apix creates every client with the same mutable
        # default cookie jar, so one child's session cookies would leak into
        # another child's requests. A fresh jar per client isolates sessions.
        client.cookies = RequestsCookieJar()
        try:
            password = account.password.get_secret_value()
            token = await cls._run_upstream_call(
                alias, client, client.get_token, account.username, password
            )
        except MaintananceError as error:
            # No cooldown: maintenance is service-wide, not a per-account
            # signal, and the check happens before the login POST.
            cls._close_client(client)
            raise RuntimeError(f"Librus is under maintenance: {error}") from error
        except RequestsJSONDecodeError as error:
            confirmed_throttle = client._session._login_throttle_confirmed
            if confirmed_throttle:
                reason = (
                    f"Librus confirmed login throttling for '{alias}' and returned "
                    "a non-JSON response; wait a few minutes before retrying."
                )
            else:
                reason = (
                    f"Librus returned a non-JSON response while authenticating '{alias}'; "
                    "this may be a transient upstream or network error."
                )
            cls._close_client(client)
            if confirmed_throttle:
                cls._start_auth_cooldown(alias, reason)
            raise ValueError(reason) from error
        except ResponseTooLargeError as error:
            confirmed_throttle = client._session._login_throttle_confirmed
            reason = f"Librus authentication response for '{alias}' exceeded the safety limit."
            if confirmed_throttle:
                reason = (
                    f"Librus confirmed login throttling for '{alias}' and returned "
                    "an oversized response; wait a few minutes before retrying."
                )
            cls._close_client(client)
            if confirmed_throttle:
                cls._start_auth_cooldown(alias, reason)
            raise ValueError(reason) from error
        except TimeoutError as error:
            raise TimeoutError(
                f"Librus authentication timed out after {UPSTREAM_OPERATION_TIMEOUT_SECONDS:.0f}s"
            ) from error
        except AUTH_ERRORS as error:
            reason = f"Failed to authenticate for '{alias}': {error}"
            cls._close_client(client)
            cls._start_auth_cooldown(alias, reason)
            raise ValueError(reason) from error
        except Exception as error:
            reason = f"Failed to authenticate for '{alias}': {error}"
            cls._close_client(client)
            raise ValueError(reason) from error

        if token is None:
            cls._close_client(client)
            raise AssertionError(f"Authentication returned None token for '{alias}'")
        cls._auth_cooldowns.pop(alias, None)
        cls._instances[alias] = client
        cls._tokens[alias] = token

        return client

    @classmethod
    def _check_auth_cooldown(cls, alias: str) -> None:
        """Fail fast during an alias-wide authentication or authorization cooldown.
        Bounds login pressure to at most one attempt per cooldown window no
        matter how aggressively a caller retries a failing tool."""
        entry = cls._auth_cooldowns.get(alias)
        if entry is None:
            return
        deadline, reason = entry
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            del cls._auth_cooldowns[alias]
            return
        raise ValueError(
            f"Authentication for '{alias}' is on cooldown for another "
            f"{int(remaining_seconds) + 1}s after an authentication or authorization "
            f"failure. Last error: {reason}"
        )

    @classmethod
    def _start_auth_cooldown(cls, alias: str, reason: str) -> None:
        cls._auth_cooldowns[alias] = (time.monotonic() + AUTH_COOLDOWN_SECONDS, reason)

    @staticmethod
    def _operation_name(func: Callable[..., Any]) -> str:
        return f"{func.__module__}.{func.__qualname__}"

    @classmethod
    def _check_operation_auth_cooldown(cls, alias: str, operation: str) -> None:
        key = (alias, operation)
        entry = cls._operation_auth_cooldowns.get(key)
        if entry is None:
            return
        deadline, reason = entry
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            del cls._operation_auth_cooldowns[key]
            return
        raise PermissionError(
            f"Operation '{operation}' for '{alias}' is on authorization cooldown for another "
            f"{int(remaining_seconds) + 1}s. Last error: {reason}"
        )

    @classmethod
    def _start_operation_auth_cooldown(cls, alias: str, operation: str, reason: str) -> None:
        now = time.monotonic()
        deadline = now + OPERATION_AUTH_COOLDOWN_SECONDS
        cls._operation_auth_cooldowns[(alias, operation)] = (deadline, reason)
        active_denials = sum(
            candidate_alias == alias and candidate_deadline > now
            for (candidate_alias, _), (
                candidate_deadline,
                _,
            ) in cls._operation_auth_cooldowns.items()
        )
        assert (alias, operation) in cls._operation_auth_cooldowns
        if active_denials >= MAX_PERSISTENT_DENIALS_PER_ALIAS:
            cls._start_auth_cooldown(alias, reason)

    @classmethod
    def _evict_client(cls, alias: str) -> None:
        """Remove cached client and token so the next call re-authenticates."""
        client = cls._instances.pop(alias, None)
        cls._tokens.pop(alias, None)
        if client is not None:
            cls._close_client(client)

    @staticmethod
    def _close_client(client: Client) -> None:
        try:
            client._session.close()
        except Exception as error:  # noqa: BLE001 - cleanup must not mask the primary failure
            # Cleanup failure must not mask an auth/timeout failure or bypass
            # the cooldown that protects the login endpoint.
            print(
                f"librus-mcp: client session cleanup failed ({type(error).__name__})",
                file=sys.stderr,
            )

    @classmethod
    def _raise_if_worker_is_running(cls, alias: str) -> None:
        worker = cls._timed_out_workers.get(alias)
        if worker is None:
            return
        if worker.done():
            cls._timed_out_workers.pop(alias, None)
            return
        raise RuntimeError(
            f"A previous Librus operation for '{alias}' is still completing after a timeout; "
            "try again shortly."
        )

    @classmethod
    def _quarantine_timed_out_worker(
        cls, alias: str, worker: asyncio.Task[Any], client: Client
    ) -> None:
        """Retain a timed-out worker until it finishes, then make the alias available."""
        cls._timed_out_workers[alias] = worker
        cached_client = cls._instances.pop(alias, None)
        cls._tokens.pop(alias, None)
        if cached_client is not None:
            assert cached_client is client, "timed-out worker must own the cached client"

        def clear_worker(completed_worker: asyncio.Task[Any]) -> None:
            if cls._timed_out_workers.get(alias) is completed_worker:
                cls._timed_out_workers.pop(alias, None)
            try:
                completed_worker.exception()
            except asyncio.CancelledError:
                pass
            finally:
                cls._close_client(client)

        worker.add_done_callback(clear_worker)

    @staticmethod
    async def _cancel_worker(cancellation: scraping.DownloadCancellation) -> None:
        cancellation.cancel()
        cancelled_error: asyncio.CancelledError | None = None
        delay = 0.0
        while True:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError as error:
                cancelled_error = error
            if cancellation.publication_is_idle():
                break
            delay = 0.001
        if cancelled_error is not None:
            raise cancelled_error

    @classmethod
    async def _run_upstream_call(
        cls,
        alias: str,
        client: Client,
        func: Callable[..., Any],
        *args,
        worker_cancellation: scraping.DownloadCancellation | None = None,
        **kwargs,
    ) -> Any:
        """Run one blocking upstream call with a deadline.

        asyncio cannot terminate a worker thread. Retiring the timed-out client
        and quarantining its alias prevents the lingering worker from overlapping
        with a subsequent request for the same account.
        """
        worker = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
        try:
            done, _ = await asyncio.wait({worker}, timeout=UPSTREAM_OPERATION_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            if worker.done():
                try:
                    worker.exception()
                finally:
                    if cls._instances.get(alias) is client:
                        cls._evict_client(alias)
                    else:
                        cls._close_client(client)
            else:
                try:
                    if worker_cancellation is not None:
                        await cls._cancel_worker(worker_cancellation)
                finally:
                    cls._quarantine_timed_out_worker(alias, worker, client)
            raise
        if worker in done:
            return worker.result()
        try:
            if worker_cancellation is not None:
                await cls._cancel_worker(worker_cancellation)
        finally:
            cls._quarantine_timed_out_worker(alias, worker, client)
        raise TimeoutError(
            f"Librus operation timed out after {UPSTREAM_OPERATION_TIMEOUT_SECONDS:.0f}s"
        )

    @classmethod
    async def _execute(
        cls,
        alias: str,
        func: Callable[..., Any],
        *args,
        retry_auth_on_failure: bool = True,
        worker_cancellation: scraping.DownloadCancellation | None = None,
        **kwargs,
    ) -> Any:
        """Execute a blocking librus-apix call on a thread, with one retry on auth failure.

        The retry exists because Librus session tokens expire after ~30 minutes
        of inactivity. When that happens, the upstream library raises
        AuthorizationError, TokenError ("Brak dostępu" page), or TokenKeyError.
        We evict the cached client and re-authenticate once. A second auth-class
        failure after that fresh login is a persistent endpoint denial, so the
        new client is evicted and that alias-operation pair enters cooldown.
        The per-alias lock serializes operations for one account; different
        accounts still run concurrently.
        """
        cls._require_account(alias)
        async with cls._client_lock(alias):
            cls._raise_if_worker_is_running(alias)
            operation = cls._operation_name(func)
            cls._check_operation_auth_cooldown(alias, operation)
            cls._check_auth_cooldown(alias)
            try:
                try:
                    client = await cls.get_client(alias)
                    return await cls._run_upstream_call(
                        alias,
                        client,
                        func,
                        client,
                        *args,
                        worker_cancellation=worker_cancellation,
                        **kwargs,
                    )
                except AUTH_ERRORS:
                    if not retry_auth_on_failure:
                        cls._evict_client(alias)
                        raise
                    # Token likely expired. Clear cache and re-authenticate once.
                    cls._evict_client(alias)
                    client = await cls.get_client(alias)
                    try:
                        return await cls._run_upstream_call(
                            alias,
                            client,
                            func,
                            client,
                            *args,
                            worker_cancellation=worker_cancellation,
                            **kwargs,
                        )
                    except AUTH_ERRORS as error:
                        cls._evict_client(alias)
                        reason = (
                            f"Librus persistently denied operation '{operation}' for '{alias}' "
                            "after a fresh login."
                        )
                        cls._start_operation_auth_cooldown(alias, operation, reason)
                        raise PermissionError(reason) from error
            except MaintananceError as error:
                raise RuntimeError(
                    f"Librus is under maintenance, try again later: {error}"
                ) from error
            except ParseError as error:
                raise RuntimeError(
                    f"Librus page could not be parsed — the site layout may have changed; "
                    f"check for librus-apix updates: {error}"
                ) from error

    @classmethod
    def list_accounts(cls) -> list[str]:
        config = cls._get_config()
        assert len(config.accounts) > 0, "Config must contain at least one account"
        return [acc.alias for acc in config.accounts]

    # --- Data Retrieval Methods ---

    @classmethod
    async def fetch_grades(cls, alias: str, sort_by: str = "all") -> dict[str, Any]:
        _require_sort_by(sort_by)
        result = await cls._execute(alias, get_grades, sort_by)
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
        cls._validate_message_page(page)
        if folder == "received":
            if page == 0:
                first_page_result = await cls._execute(
                    alias, librus_optimizations.get_received_first_page
                )
                max_page, messages = cls._validate_first_page_result(first_page_result)
            else:
                max_page = await cls._execute(alias, get_message_max_page)
                assert isinstance(max_page, int), "get_max_page_number must return an int"
                if page > max_page:
                    raise ValueError(f"page {page} exceeds max_page {max_page}")
                messages = await cls._execute(alias, get_received, page)
        elif folder == "sent":
            # Librus exposes no page counter for the sent folder.
            max_page = None
            messages = await cls._execute(alias, get_sent, page)
        else:
            raise ValueError(f"folder must be one of {MESSAGE_FOLDERS}, got: '{folder}'")
        messages, truncated = cls._bounded_message_batch(messages)
        return {
            "messages": messages,
            "folder": folder,
            "page": page,
            "max_page": max_page,
            "truncated": truncated,
        }

    @classmethod
    def _validate_message_page(cls, page: Any) -> None:
        if not isinstance(page, int) or isinstance(page, bool):
            raise TypeError(f"page must be an integer, got: {type(page).__name__}")
        if not 0 <= page <= MAX_MESSAGE_PAGE:
            raise ValueError(f"page must be between 0 and {MAX_MESSAGE_PAGE}, got: {page}")

    @staticmethod
    def _validate_first_page_result(result: Any) -> tuple[int, list[Any]]:
        assert isinstance(result, tuple), "first-page fetch must return a tuple"
        assert len(result) == 2, "first-page fetch must return (max_page, items)"
        max_page, items = result
        assert isinstance(max_page, int), "first-page max_page must be an int"
        assert max_page >= 0, "first-page max_page must be nonnegative"
        assert isinstance(items, list), "first-page fetch must return a list of items"
        return max_page, items

    @staticmethod
    def _bounded_message_batch(messages: Any) -> tuple[list[Any], bool]:
        assert isinstance(messages, list), "message fetch must return a list"
        truncated = len(messages) > MESSAGES_PER_PAGE
        return messages[:MESSAGES_PER_PAGE], truncated

    @classmethod
    async def fetch_all_messages(cls, alias: str, folder: str = "received") -> dict[str, Any]:
        """Fetch every message in a folder, newest first, bounded by
        MAX_ALL_MESSAGE_PAGES. Returns truncated=True when the bound cut
        the mailbox short."""
        if folder == "received":
            messages, pages_fetched, truncated = await cls._fetch_all_received(alias)
        elif folder == "sent":
            messages, pages_fetched, truncated = await cls._fetch_all_sent(alias)
        else:
            raise ValueError(f"folder must be one of {MESSAGE_FOLDERS}, got: '{folder}'")
        return {
            "messages": messages,
            "folder": folder,
            "pages_fetched": pages_fetched,
            "truncated": truncated,
        }

    @classmethod
    async def _fetch_all_received(cls, alias: str) -> tuple[list[Any], int, bool]:
        first_page_result = await cls._execute(alias, librus_optimizations.get_received_first_page)
        max_page, first_page = cls._validate_first_page_result(first_page_result)
        first_page, page_truncated = cls._bounded_message_batch(first_page)
        messages = first_page[:MAX_ALL_MESSAGE_ITEMS]
        if page_truncated:
            return messages, 1, True
        if len(first_page) >= MAX_ALL_MESSAGE_ITEMS:
            return messages, 1, max_page > 0
        last_page = min(max_page, MAX_ALL_MESSAGE_PAGES - 1)
        truncated = max_page >= MAX_ALL_MESSAGE_PAGES
        pages_fetched = 1
        for page in range(1, last_page + 1):
            batch = await cls._execute(alias, get_received, page)
            batch, page_truncated = cls._bounded_message_batch(batch)
            remaining = MAX_ALL_MESSAGE_ITEMS - len(messages)
            messages.extend(batch[:remaining])
            pages_fetched += 1
            if page_truncated or len(batch) > remaining:
                return messages, pages_fetched, True
            if len(messages) == MAX_ALL_MESSAGE_ITEMS:
                return messages, pages_fetched, page < max_page
        return messages, pages_fetched, truncated

    @classmethod
    async def _fetch_all_sent(cls, alias: str) -> tuple[list[Any], int, bool]:
        """The sent folder has no page counter, so iterate until a short page.
        Librus clamps out-of-range pages to the last page instead of returning
        an empty list, so a repeated page also terminates the loop."""
        messages: list[Any] = []
        previous_hrefs: list[str] | None = None
        pages_fetched = 0
        truncated = True
        for page in range(MAX_ALL_MESSAGE_PAGES):
            batch = await cls._execute(alias, get_sent, page)
            batch, page_truncated = cls._bounded_message_batch(batch)
            # Upstream falls back to href="" when its parse heuristic fails;
            # two distinct pages of all-empty hrefs would compare equal and
            # stop early - acceptable, since such pages are already unusable.
            hrefs = [message.href for message in batch]
            if hrefs == previous_hrefs:
                truncated = False
                break
            remaining = MAX_ALL_MESSAGE_ITEMS - len(messages)
            messages.extend(batch[:remaining])
            pages_fetched += 1
            previous_hrefs = hrefs
            if page_truncated or len(batch) > remaining:
                break
            if len(batch) != MESSAGES_PER_PAGE:
                truncated = False
                break
        return messages, pages_fetched, truncated

    @classmethod
    async def fetch_message_content(cls, alias: str, message_id: str) -> dict[str, str]:
        """Fetch a message by its ID (from the 'href' field), returning the
        full upstream metadata: author, title, date, and content."""
        _require_message_id(message_id)
        message_data = await cls._execute(alias, message_content, message_id)
        assert message_data is not None, "message_content returned None"
        return {
            "author": message_data.author,
            "title": message_data.title,
            "date": message_data.date,
            "content": message_data.content,
        }

    @classmethod
    async def fetch_attendance(cls, alias: str, sort_by: str = "all") -> list[Any]:
        _require_sort_by(sort_by)
        attendance = await cls._execute(alias, get_attendance, sort_by)
        assert isinstance(attendance, list), "get_attendance must return a list"
        assert all(isinstance(semester, list) for semester in attendance), (
            "get_attendance must group records into semester lists"
        )
        record_count = sum(len(semester) for semester in attendance)
        if record_count > librus_optimizations.MAX_ATTENDANCE_RECORDS:
            raise ValueError(
                f"attendance record count exceeds {librus_optimizations.MAX_ATTENDANCE_RECORDS}"
            )
        return attendance

    @classmethod
    async def fetch_attendance_detail(cls, alias: str, detail_url: str) -> dict[str, str]:
        """Fetch details of one attendance entry (from its 'href' field)."""
        _require_message_id(detail_url, "detail_url")
        detail = await cls._execute(alias, get_attendance_detail, detail_url)
        assert isinstance(detail, dict), "get_detail must return a dict"
        return detail

    @classmethod
    async def fetch_attendance_frequency(cls, alias: str) -> dict[str, float]:
        """Fetch attendance frequency ratios (0..1) per semester and overall."""
        try:
            result = await cls._execute(alias, get_attendance_frequency)
        except KeyError as error:
            # Upstream hardcodes the gateway attendance-type map; schools can
            # define custom types (seen live: ID 4766), which KeyError out of
            # it. Per-subject frequency scrapes a page instead and still works.
            raise RuntimeError(
                f"librus-apix cannot compute overall attendance frequency for "
                f"'{alias}': the school uses a custom attendance type (ID {error}) "
                f"missing from the library's hardcoded map. "
                f"Use get_subject_frequency instead."
            ) from error
        assert isinstance(result, tuple), "get_attendance_frequency must return a tuple"
        assert len(result) == 3, "get_attendance_frequency must return three ratios"
        first_semester, second_semester, overall = result
        return {
            "first_semester": first_semester,
            "second_semester": second_semester,
            "overall": overall,
        }

    @classmethod
    async def fetch_subject_frequency(
        cls, alias: str, start: str | None = None, end: str | None = None
    ) -> dict[str, Any]:
        """Fetch per-subject attendance frequency, optionally filtered by date range."""
        kwargs: dict[str, Any] = {}
        start_date = _parse_date(start, "start") if start is not None else None
        end_date = _parse_date(end, "end") if end is not None else None
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError(f"start {start} is after end {end}")
        if start_date is not None:
            kwargs["start"] = start_date
        if end_date is not None:
            kwargs["end"] = end_date
        frequency = await cls._execute(alias, librus_optimizations.get_subject_frequency, **kwargs)
        assert isinstance(frequency, dict), "get_subject_frequency must return a dict"
        return dict(frequency)

    @classmethod
    async def fetch_homework(
        cls, alias: str, date_from: str | None = None, date_to: str | None = None
    ) -> list[Any]:
        """Fetch homework for a date range; defaults to today through +14 days."""
        if date_from is None and date_to is None:
            today = datetime.now(SCHOOL_TIME_ZONE).date()
            date_from = today.strftime(DATE_FORMAT)
            date_to = (today + timedelta(days=14)).strftime(DATE_FORMAT)
        if date_from is None or date_to is None:
            raise ValueError("date_from and date_to must be provided together")
        start = _parse_date(date_from, "date_from")
        end = _parse_date(date_to, "date_to")
        if start > end:
            raise ValueError(f"date_from {date_from} is after date_to {date_to}")
        if (end - start).days > MAX_HOMEWORK_RANGE_DAYS:
            raise ValueError(f"date range exceeds {MAX_HOMEWORK_RANGE_DAYS} days")
        homework = await cls._execute(alias, get_homework, date_from, date_to)
        assert isinstance(homework, list), "get_homework must return a list"
        return homework

    @classmethod
    async def fetch_homework_detail(cls, alias: str, detail_url: str) -> Any:
        """Fetch full details of a specific homework assignment."""
        _require_message_id(detail_url, "detail_url")
        detail = await cls._execute(alias, homework_detail, detail_url)
        assert detail is not None, "homework_detail returned None"
        return detail

    @classmethod
    async def fetch_schedule(cls, alias: str, month: str, year: str) -> dict[int, Any]:
        _require_non_empty(month, "month")
        _require_non_empty(year, "year")
        if not month.isdigit() or not 1 <= int(month) <= 12:
            raise ValueError(f"month must be 1-12, got: '{month}'")
        if not year.isdigit() or not 2000 < int(year) <= 2100:
            raise ValueError(f"year must be a year between 2001 and 2100, got: '{year}'")

        schedule = await cls._execute(alias, get_schedule, month, year, include_empty=False)
        assert isinstance(schedule, dict), "get_schedule must return a dict"
        return dict(schedule)

    @classmethod
    async def fetch_schedule_detail(cls, alias: str, href: str) -> dict[str, str]:
        """Fetch details of one schedule event by its 'href' field
        ('prefix/suffix', e.g. 'szczegoly/12345')."""
        _require_non_empty(href, "href")
        if SCHEDULE_HREF_PATTERN.match(href) is None:
            raise ValueError(
                f"href must look like 'prefix/id' from a schedule event, got: '{href}'"
            )
        prefix, _, detail_url = href.partition("/")
        detail = await cls._execute(alias, schedule_detail, prefix, detail_url)
        assert isinstance(detail, dict), "schedule_detail must return a dict"
        return detail

    @classmethod
    async def fetch_timetable(cls, alias: str, monday: str | None = None) -> list[Any]:
        """Fetch the timetable for the week starting at `monday`
        (YYYY-MM-DD, must be a Monday); defaults to the current week."""
        if monday is None:
            today = datetime.now(SCHOOL_TIME_ZONE).date()
            monday_date = today - timedelta(days=today.weekday())
        else:
            monday_date = _parse_date(monday, "monday")
            if monday_date.weekday() != 0:
                raise ValueError(f"'{monday}' is not a Monday; pass the first day of the week")
        timetable = await cls._execute(alias, get_timetable, monday_date)
        assert isinstance(timetable, list), "get_timetable must return a list"
        return timetable

    @classmethod
    async def fetch_announcements(cls, alias: str) -> list[Any]:
        announcements = await cls._execute(alias, get_announcements)
        assert isinstance(announcements, list), "get_announcements must return a list"
        return announcements

    @classmethod
    async def fetch_completed_lessons(cls, alias: str, date_from: str, date_to: str) -> list[Any]:
        """Fetch completed lessons for a date range, iterating all pages."""
        start = _parse_date(date_from, "date_from")
        end = _parse_date(date_to, "date_to")
        if start > end:
            raise ValueError(f"date_from {date_from} is after date_to {date_to}")
        if (end - start).days > MAX_COMPLETED_LESSONS_RANGE_DAYS:
            raise ValueError(f"date range exceeds {MAX_COMPLETED_LESSONS_RANGE_DAYS} days")

        first_page_result = await cls._execute(
            alias,
            librus_optimizations.get_completed_first_page,
            date_from,
            date_to,
        )
        max_page, first_page = cls._validate_first_page_result(first_page_result)
        page_count = max_page + 1
        if page_count > MAX_COMPLETED_LESSONS_PAGES:
            raise ValueError(
                f"range spans {page_count} pages of lessons "
                f"(limit {MAX_COMPLETED_LESSONS_PAGES}); narrow the date range"
            )

        all_lessons = list(first_page)
        if len(all_lessons) > MAX_COMPLETED_LESSONS_ITEMS:
            raise ValueError(
                f"completed lesson count exceeds {MAX_COMPLETED_LESSONS_ITEMS}; "
                "narrow the date range"
            )
        for page in range(1, max_page + 1):
            lessons = await cls._execute(alias, get_completed, date_from, date_to, page)
            assert isinstance(lessons, list), "get_completed must return a list"
            if len(all_lessons) + len(lessons) > MAX_COMPLETED_LESSONS_ITEMS:
                raise ValueError(
                    f"completed lesson count exceeds {MAX_COMPLETED_LESSONS_ITEMS}; "
                    "narrow the date range"
                )
            all_lessons.extend(lessons)
        return all_lessons

    @classmethod
    async def fetch_student_information(cls, alias: str) -> Any:
        """Fetch student profile information (name, class, tutor, school, lucky number)."""
        info = await cls._execute(alias, get_student_information)
        assert info is not None, "get_student_information returned None"
        return info

    @classmethod
    async def fetch_recent_schedule_events(cls, alias: str) -> list[Any]:
        """Fetch read-once schedule events through the state transaction."""
        cls._require_account(alias)
        state_dir = cls._get_config().state_dir
        async with cls._notification_lock(alias):
            lock_descriptor = await cls._acquire_notification_state_lock(state_dir, alias)
            try:
                seen_ids = load_notification_ids(state_dir, alias)
                if seen_ids is None:
                    seen_ids = NotificationIds([], [], [], [], [], [])
                pending = load_pending_schedule_events(state_dir, alias)
                checkpointed: list[RecentEvent] = []
                checkpoint = cls._schedule_checkpoint(state_dir, alias, checkpointed)
                result = await cls._execute(
                    alias,
                    librus_optimizations.get_recent_schedule_events,
                    seen_ids.schedule,
                    pending,
                    checkpoint,
                )
                assert isinstance(result, tuple), "recent schedule fetch must return a tuple"
                assert len(result) == 2, "recent schedule fetch must return (events, ids)"
                events, seen_ids.schedule = result
                save_notification_ids(state_dir, alias, seen_ids)
                clear_pending_schedule_events(state_dir, alias, [*pending, *checkpointed])
            finally:
                release_notification_state_lock(lock_descriptor)
        return events

    @classmethod
    async def fetch_new_notifications(cls, alias: str) -> dict[str, Any]:
        """Diff current Librus data against persisted seen-IDs and return what is new.

        First run for an alias has no state file: diff against empty IDs, which
        returns the items since the last Librus login as baseline. We deliberately
        avoid get_initial_notification_data — it scrapes /uczen/index, which
        returns 403 for parent (rodzic) accounts.
        """
        cls._require_account(alias)
        config = cls._get_config()
        state_dir = config.state_dir
        async with cls._notification_lock(alias):
            lock_descriptor = await cls._acquire_notification_state_lock(state_dir, alias)
            try:
                seen_ids = load_notification_ids(state_dir, alias)
                first_run = seen_ids is None
                if seen_ids is None:
                    seen_ids = NotificationIds([], [], [], [], [], [])
                pending = load_pending_schedule_events(state_dir, alias)
                checkpointed: list[RecentEvent] = []
                checkpoint = cls._schedule_checkpoint(state_dir, alias, checkpointed)
                result = await cls._execute(
                    alias,
                    librus_optimizations.get_new_notifications,
                    seen_ids,
                    LibrusTimeoutSession,
                    pending,
                    checkpoint,
                )
                assert isinstance(result, tuple), "notification fetch must return a tuple"
                assert len(result) == 2, "notification fetch must return (data, ids)"
                data, updated_ids = result
                save_notification_ids(state_dir, alias, updated_ids)
                clear_pending_schedule_events(state_dir, alias, [*pending, *checkpointed])
            finally:
                release_notification_state_lock(lock_descriptor)
        return {"first_run": first_run, "new": data}

    @staticmethod
    def _schedule_checkpoint(
        state_dir: Path, alias: str, checkpointed: list[RecentEvent]
    ) -> Callable[[list[RecentEvent]], None]:
        """Build an idempotent callback that runs inside the upstream worker."""

        def checkpoint(events: list[RecentEvent]) -> None:
            save_pending_schedule_events(state_dir, alias, events)
            checkpointed.extend(events)

        return checkpoint

    @classmethod
    async def _acquire_notification_state_lock(cls, state_dir: Path, alias: str) -> int:
        """Acquire a cross-process state lock without blocking cancellation.

        Each attempt is non-blocking and the bounded sleep yields to the event
        loop, so a cancelled MCP request cannot orphan a lock descriptor in a
        background thread.
        """
        for _ in range(NOTIFICATION_LOCK_MAX_ATTEMPTS):
            descriptor = try_acquire_notification_state_lock(state_dir, alias)
            if descriptor is not None:
                return descriptor
            await asyncio.sleep(NOTIFICATION_LOCK_RETRY_SECONDS)
        raise TimeoutError("notification state is locked by another MCP process; try again later")

    @classmethod
    async def fetch_recipient_groups(cls, alias: str) -> list[str]:
        """Fetch recipient group identifiers available for sending messages."""
        groups = await cls._execute(alias, recipient_groups)
        assert isinstance(groups, list), "recipient_groups must return a list"
        return groups

    @classmethod
    async def fetch_recipients(cls, alias: str, group: str) -> dict[str, str]:
        """Fetch recipients (name -> id) belonging to a recipient group."""
        _require_non_empty(group, "group")
        recipients = await cls._execute(alias, get_recipients, group)
        assert isinstance(recipients, dict), "get_recipients must return a dict"
        return recipients

    @classmethod
    def validate_send_message_args(
        cls, alias: str, title: str, content: str, recipient_ids: list[str]
    ) -> None:
        """Validate send_message inputs without sending. The server calls this
        at the preview step so a bad request fails before a confirmation token
        is issued, not after the human already approved the preview."""
        cls._require_account(alias)
        title = _require_non_empty(title, "title")
        content = _require_non_empty(content, "content")
        if len(title) > MAX_SEND_TITLE_LENGTH:
            raise ValueError(f"title exceeds {MAX_SEND_TITLE_LENGTH} characters")
        if len(content) > MAX_SEND_CONTENT_LENGTH:
            raise ValueError(f"content exceeds {MAX_SEND_CONTENT_LENGTH} characters")
        if not isinstance(recipient_ids, list) or not recipient_ids:
            raise ValueError("recipient_ids must be a non-empty list")
        if len(recipient_ids) > MAX_SEND_RECIPIENTS:
            raise ValueError(f"implausible recipient count: {len(recipient_ids)}")
        for recipient_id in recipient_ids:
            recipient_id = _require_non_empty(recipient_id, "each recipient_id")
            if len(recipient_id) > MAX_RECIPIENT_ID_LENGTH:
                raise ValueError(
                    f"each recipient_id must be at most {MAX_RECIPIENT_ID_LENGTH} digits"
                )
            if re.fullmatch(r"[0-9]+", recipient_id) is None:
                raise ValueError("each recipient_id must contain only ASCII digits")
        if len(set(recipient_ids)) < len(recipient_ids):
            raise ValueError("recipient_ids must be unique")
        payload_size = len(title.encode("utf-8")) + len(content.encode("utf-8"))
        payload_size += sum(len(recipient_id.encode("ascii")) for recipient_id in recipient_ids)
        if payload_size > MAX_SEND_PAYLOAD_BYTES:
            raise ValueError(f"message payload exceeds {MAX_SEND_PAYLOAD_BYTES} bytes")

    @classmethod
    async def send_message_to(
        cls, alias: str, title: str, content: str, recipient_ids: list[str]
    ) -> dict[str, Any]:
        """Send a message via the school messaging system. Write action."""
        cls.validate_send_message_args(alias, title, content, recipient_ids)
        try:
            result = await cls._execute(
                alias,
                send_message,
                title,
                content,
                recipient_ids,
                retry_auth_on_failure=False,
            )
            if not isinstance(result, tuple) or len(result) != 2:
                raise RuntimeError("librus-apix returned an invalid send_message result")
            _, status_message = result
            if not isinstance(status_message, str):
                raise TypeError("librus-apix returned a non-string send_message status")
            # The negative check must run first: "nie została wysłana"
            # contains "została wysłana" as a substring.
            if "nie została" in status_message:
                return {"success": False, "result": status_message}
            if "została wysłana" in status_message:
                return {"success": True, "result": status_message}
            raise RuntimeError(
                f"unrecognized send_message result (message may or may not have been "
                f"delivered — check the sent folder): '{status_message}'"
            )
        except asyncio.CancelledError as error:
            raise RuntimeError(
                "Librus send delivery is uncertain and was not retried to avoid duplicate delivery; "
                "check the sent folder before trying again."
            ) from error
        except Exception as error:
            raise RuntimeError(
                "Librus send delivery is uncertain and was not retried to avoid duplicate delivery; "
                f"check the sent folder before trying again. Upstream error: {error}"
            ) from error

    @classmethod
    async def fetch_message_attachments(cls, alias: str, message_id: str) -> list[Any]:
        """List attachments of a message (own scraping; librus-apix lacks this)."""
        _require_message_id(message_id)
        attachments = await cls._execute(alias, scraping.get_attachments, message_id)
        assert isinstance(attachments, list), "get_attachments must return a list"
        return attachments

    @classmethod
    async def download_message_attachment(
        cls, alias: str, message_id: str, file_id: str
    ) -> dict[str, Any]:
        """Download one message attachment to the configured download dir."""
        _require_message_id(message_id)
        _require_message_id(file_id, "file_id")
        config = cls._get_config()
        cancellation = scraping.DownloadCancellation()
        info = await cls._execute(
            alias,
            scraping.download_attachment,
            message_id,
            file_id,
            config.download_dir,
            cancellation,
            worker_cancellation=cancellation,
        )
        assert isinstance(info, dict), "download_attachment must return a dict"
        return info

    @classmethod
    async def fetch_final_grades(cls, alias: str) -> list[Any]:
        """Fetch end-of-year grade columns (midterm, predicted annual, annual).

        Own scraping: librus-apix parses only current grades and skips the
        (I)/(R)/R summary columns of the grades table.
        """
        grades = await cls._execute(alias, scraping.get_final_grades)
        assert isinstance(grades, list), "get_final_grades must return a list"
        return grades

    @classmethod
    async def fetch_behaviour_notes(cls, alias: str) -> list[Any]:
        """Fetch behaviour notes (uwagi) — own scraping; librus-apix lacks this."""
        notes = await cls._execute(alias, scraping.get_behaviour_notes)
        assert isinstance(notes, list), "get_behaviour_notes must return a list"
        return notes
