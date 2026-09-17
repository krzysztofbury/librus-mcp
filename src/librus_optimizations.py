"""Bounded replacements for expensive multi-request librus-apix operations."""

import asyncio
import copy
import json
import re
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout, CookieJar
from bs4 import BeautifulSoup
from librus_apix.announcements import get_announcements
from librus_apix.attendance import get_attendance
from librus_apix.client import Client
from librus_apix.completed_lessons import _create_lesson as create_completed_lesson
from librus_apix.exceptions import AuthorizationError, ParseError
from librus_apix.grades import get_grades
from librus_apix.helpers import no_access_check
from librus_apix.homework import get_homework
from librus_apix.messages import get_received
from librus_apix.messages import parse as parse_messages
from librus_apix.notifications import (
    NotificationData,
    NotificationIds,
    _parse_announcements_notification,
    _parse_attendance_notification,
    _parse_grades_notifications,
    _parse_homework_notification,
    _parse_messages_notification,
)
from librus_apix.schedule import RecentEvent, get_recently_added_schedule
from requests.cookies import RequestsCookieJar
from yarl import URL

from src.notification_state import schedule_event_id
from src.response_limits import (
    MAX_RESPONSE_BODY_BYTES,
    RESPONSE_READ_CHUNK_BYTES,
    ResponseTooLargeError,
)

GATEWAY_CONCURRENCY = 5
GATEWAY_RETRIES = 2
GATEWAY_REQUEST_TIMEOUT_SECONDS = 15.0
GATEWAY_RESOLUTION_TIMEOUT_SECONDS = 50.0
NOTIFICATION_CONCURRENCY = 3
MAX_GATEWAY_RESPONSE_BYTES = MAX_RESPONSE_BODY_BYTES
MAX_SCHEDULE_EVENTS_PER_CALL = 500
MAX_ATTENDANCE_RECORDS = 10_000
MAX_UNIQUE_LESSON_IDS = 2_000
MAX_UNIQUE_SUBJECT_IDS = 500
SCHOOL_TIME_ZONE = ZoneInfo("Europe/Warsaw")

ATTENDANCE_TYPES = {
    "1": "nb",
    "2": "sp",
    "3": "u",
    "4": "zw",
    "100": "ob",
    "1266": "wy",
    "2022": "k",
    "2829": "sz",
}


def get_subject_frequency(
    client: Client, start: date | None = None, end: date | None = None
) -> dict[str, float]:
    """Resolve each unique lesson and subject once, with bounded concurrency."""
    client.refresh_oauth()
    attendances = client.get(client.GATEWAY_API_ATTENDANCE).json()["Attendances"]
    assert isinstance(attendances, list), "gateway Attendances must be a list"
    if len(attendances) > MAX_ATTENDANCE_RECORDS:
        raise ValueError(f"attendance record count exceeds {MAX_ATTENDANCE_RECORDS}")
    filtered = _filter_attendances(attendances, start, end)
    resolved = asyncio.run(
        asyncio.wait_for(
            _resolve_subjects(client, filtered), timeout=GATEWAY_RESOLUTION_TIMEOUT_SECONDS
        )
    )
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for subject, absence_type in resolved:
        counts[subject][absence_type] += 1
    frequencies: dict[str, float] = {}
    for subject, subject_counts in counts.items():
        attended = subject_counts.get("ob", 0) + subject_counts.get("sp", 0)
        unattended = sum(subject_counts.get(key, 0) for key in ("nb", "u", "zw"))
        total = attended + unattended
        frequencies[subject] = round(attended / total * 100, 2) if total else 100.0
    return frequencies


def _filter_attendances(
    attendances: list[dict[str, Any]], start: date | None, end: date | None
) -> list[dict[str, Any]]:
    if start is None and end is None:
        return attendances
    filtered: list[dict[str, Any]] = []
    for attendance in attendances:
        attendance_date = date.fromisoformat(attendance["Date"])
        if start is not None and attendance_date < start:
            continue
        if end is not None and attendance_date > end:
            continue
        filtered.append(attendance)
    return filtered


async def _resolve_subjects(
    client: Client, attendances: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    lesson_ids = list(dict.fromkeys(attendance["Lesson"]["Id"] for attendance in attendances))
    if len(lesson_ids) > MAX_UNIQUE_LESSON_IDS:
        raise ValueError(f"unique lesson count exceeds {MAX_UNIQUE_LESSON_IDS}")
    if not lesson_ids:
        return []
    semaphore = asyncio.Semaphore(GATEWAY_CONCURRENCY)
    proxy = client.proxy.get("https") or client.proxy.get("http")
    timeout = ClientTimeout(total=GATEWAY_REQUEST_TIMEOUT_SECONDS)
    cookie_jar = CookieJar()
    cookie_jar.update_cookies(dict(client._session.cookies), response_url=URL(client.BASE_URL))
    async with ClientSession(
        cookie_jar=cookie_jar,
        headers=dict(client._session.headers),
        timeout=timeout,
    ) as session:
        lesson_payloads = await asyncio.gather(
            *[
                _request_json(
                    session,
                    f"{client.BASE_URL}/gateway/api/2.0/Lessons/{lesson_id}",
                    semaphore,
                    proxy,
                )
                for lesson_id in lesson_ids
            ]
        )
        lesson_subjects = {
            lesson_id: payload["Lesson"]["Subject"]["Id"]
            for lesson_id, payload in zip(lesson_ids, lesson_payloads, strict=True)
        }
        subject_ids = list(dict.fromkeys(lesson_subjects.values()))
        if len(subject_ids) > MAX_UNIQUE_SUBJECT_IDS:
            raise ValueError(f"unique subject count exceeds {MAX_UNIQUE_SUBJECT_IDS}")
        subject_payloads = await asyncio.gather(
            *[
                _request_json(
                    session,
                    f"{client.BASE_URL}/gateway/api/2.0/Subjects/{subject_id}",
                    semaphore,
                    proxy,
                )
                for subject_id in subject_ids
            ]
        )
    subject_names = {
        subject_id: payload["Subject"]["Name"]
        for subject_id, payload in zip(subject_ids, subject_payloads, strict=True)
    }
    return [
        (
            subject_names[lesson_subjects[attendance["Lesson"]["Id"]]],
            ATTENDANCE_TYPES.get(str(attendance["Type"]["Id"]), "unknown"),
        )
        for attendance in attendances
    ]


async def _request_json(
    session: ClientSession,
    url: str,
    semaphore: asyncio.Semaphore,
    proxy: str | None,
) -> dict[str, Any]:
    for attempt in range(GATEWAY_RETRIES):
        try:
            async with semaphore, session.get(url, proxy=proxy, allow_redirects=False) as response:
                if response.status in (401, 403):
                    raise AuthorizationError(
                        f"gateway authorization failed: HTTP {response.status}"
                    )
                if 300 <= response.status < 400:
                    raise AuthorizationError(
                        f"gateway authentication redirect: HTTP {response.status}"
                    )
                response.raise_for_status()
                if (
                    response.content_length is not None
                    and response.content_length > MAX_GATEWAY_RESPONSE_BYTES
                ):
                    raise ResponseTooLargeError(
                        "Librus gateway response body is too large "
                        f"(maximum {MAX_GATEWAY_RESPONSE_BYTES} bytes)"
                    )
                encoded_payload = bytearray()
                async for chunk in response.content.iter_chunked(RESPONSE_READ_CHUNK_BYTES):
                    encoded_payload.extend(chunk)
                    if len(encoded_payload) > MAX_GATEWAY_RESPONSE_BYTES:
                        raise ResponseTooLargeError(
                            "Librus gateway response body is too large "
                            f"(maximum {MAX_GATEWAY_RESPONSE_BYTES} bytes)"
                        )
                try:
                    payload = json.loads(encoded_payload)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    raise ParseError("gateway response is not valid JSON") from error
                if not isinstance(payload, dict):
                    raise ParseError("gateway response must be an object")
                return payload
        except AuthorizationError:
            raise
        except ClientResponseError as error:
            if 400 <= error.status < 500:
                raise
            if attempt == GATEWAY_RETRIES - 1:
                raise
            await asyncio.sleep(0.5 * (2**attempt))
        except ClientError, TimeoutError:
            if attempt == GATEWAY_RETRIES - 1:
                raise
            await asyncio.sleep(0.5 * (2**attempt))
    raise AssertionError("gateway retry loop must return or raise")


def get_new_notifications(
    client: Client,
    seen: NotificationIds,
    session_factory: Callable[[], Any],
    pending_schedule: list[RecentEvent] | None = None,
    schedule_checkpoint: Callable[[list[RecentEvent]], None] | None = None,
) -> tuple[NotificationData, NotificationIds]:
    """Fetch safe categories first, then checkpoint the read-once schedule."""
    today = datetime.now(SCHOOL_TIME_ZONE).date()
    calls = {
        "grades": (get_grades, ("last_login",)),
        "attendance": (get_attendance, ("last_login",)),
        "messages": (get_received, (0,)),
        "announcements": (get_announcements, ()),
        "homework": (
            get_homework,
            (
                (today - timedelta(days=7)).strftime("%Y-%m-%d"),
                today.strftime("%Y-%m-%d"),
            ),
        ),
    }
    with ThreadPoolExecutor(max_workers=NOTIFICATION_CONCURRENCY) as executor:
        futures = {
            name: executor.submit(_call_with_clone, client, session_factory, function, *args)
            for name, (function, args) in calls.items()
        }
        results = {name: future.result() for name, future in futures.items()}
    schedule = [] if pending_schedule else get_recently_added_schedule(client)
    _checkpoint_and_bound_schedule(pending_schedule or [], schedule, schedule_checkpoint)
    grades, _, _ = results["grades"]
    homework = results["homework"][::-1]
    new_schedule, seen_schedule = _parse_schedule_notifications(
        pending_schedule or [], schedule, seen.schedule
    )
    new_grades, seen_grades = _parse_grades_notifications(grades, seen.grades)
    new_attendance, seen_attendance = _parse_attendance_notification(
        results["attendance"], seen.attendance
    )
    new_messages, seen_messages = _parse_messages_notification(results["messages"], seen.messages)
    new_announcements, seen_announcements = _parse_announcements_notification(
        results["announcements"], seen.announcements
    )
    new_homework, seen_homework = _parse_homework_notification(homework, seen.homework)
    return NotificationData(
        new_grades,
        new_attendance,
        new_messages,
        new_announcements,
        new_schedule,
        new_homework,
    ), NotificationIds(
        seen_grades,
        seen_attendance,
        seen_messages,
        seen_announcements,
        seen_schedule,
        seen_homework,
    )


def get_recent_schedule_events(
    client: Client,
    seen_ids: list[str],
    pending_schedule: list[RecentEvent],
    schedule_checkpoint: Callable[[list[RecentEvent]], None],
) -> tuple[list[RecentEvent], list[str]]:
    """Fetch, checkpoint, and diff the upstream read-once schedule view."""
    schedule = [] if pending_schedule else get_recently_added_schedule(client)
    _checkpoint_and_bound_schedule(pending_schedule, schedule, schedule_checkpoint)
    return _parse_schedule_notifications(pending_schedule, schedule, seen_ids)


def _checkpoint_and_bound_schedule(
    pending: list[RecentEvent],
    fresh: list[RecentEvent],
    checkpoint: Callable[[list[RecentEvent]], None] | None,
) -> None:
    if not isinstance(fresh, list):
        raise ParseError("recent schedule response must be a list")
    if checkpoint is not None:
        checkpoint(fresh)
    event_count = len(pending) + len(fresh)
    if event_count > MAX_SCHEDULE_EVENTS_PER_CALL:
        raise ValueError(
            f"recent schedule returned {event_count} events, exceeding the per-call "
            f"limit of {MAX_SCHEDULE_EVENTS_PER_CALL}; consumed events were preserved "
            "and will drain across later calls"
        )


def _parse_schedule_notifications(
    pending: list[RecentEvent], fresh: list[RecentEvent], seen_ids: list[str]
) -> tuple[list[RecentEvent], list[str]]:
    """Prefer spooled events over seen state so partial commits cannot hide them."""
    pending_ids = {schedule_event_id(event) for event in pending}
    unique_events: dict[str, RecentEvent] = {}
    for event in [*pending, *fresh]:
        unique_events.setdefault(schedule_event_id(event), event)

    new_schedule: list[RecentEvent] = []
    for event_id, event in unique_events.items():
        was_seen = event_id in seen_ids
        if event_id not in seen_ids:
            seen_ids.append(event_id)
        if event_id in pending_ids or not was_seen:
            new_schedule.append(event)
    return new_schedule, seen_ids


def _call_with_clone(
    client: Client,
    session_factory: Callable[[], Any],
    function: Callable[..., Any],
    *args: Any,
) -> Any:
    clone = copy.copy(client)
    clone.cookies = RequestsCookieJar()
    clone.cookies.update(client.cookies)
    clone._session = session_factory()
    try:
        return function(clone, *args)
    finally:
        clone._session.close()


def get_received_first_page(client: Client) -> tuple[int, list[Any]]:
    """Parse received messages and their last page index from one GET."""
    soup = no_access_check(BeautifulSoup(client.get(client.MESSAGE_URL).text, "lxml"))
    return _last_page_index(soup), parse_messages(soup)


def get_completed_first_page(client: Client, date_from: str, date_to: str) -> tuple[int, list[Any]]:
    """Parse completed lessons and their last page index from one POST."""
    data = {
        "data1": date_from,
        "data2": date_to,
        "filtruj_id_przedmiotu": -1,
        "numer_strony1001": 0,
        "porcjowanie_pojemnik1001": 1001,
    }
    soup = no_access_check(
        BeautifulSoup(client.post(client.COMPLETED_LESSONS_URL, data=data).text, "lxml")
    )
    rows = soup.select('table[class="decorated"] > tbody > tr')
    return _last_page_index(soup), [create_completed_lesson(row) for row in rows]


def _last_page_index(soup: BeautifulSoup) -> int:
    pages = soup.select_one("div.pagination > span")
    if pages is None:
        return 0
    match = re.search(r"z\s*(\d+)", pages.get_text().replace("\xa0", ""))
    if match is None:
        raise ParseError("Error while trying to parse the maximum page number")
    return max(int(match.group(1)) - 1, 0)
