import asyncio
import hashlib
import json
import threading
from datetime import date
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientResponseError
from librus_apix.exceptions import AuthorizationError, ParseError
from librus_apix.notifications import NotificationIds
from librus_apix.schedule import RecentEvent
from yarl import URL

from src import librus_optimizations
from src.notification_state import schedule_event_id


class FakeJsonResponse:
    status = 200

    def __init__(self, payload, activity):
        self.payload = payload
        self.activity = activity
        self.content_length = None
        self.content = FakeContent(json.dumps(payload).encode())

    async def __aenter__(self):
        self.activity["active"] += 1
        self.activity["max"] = max(self.activity["max"], self.activity["active"])
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *args):
        self.activity["active"] -= 1

    def raise_for_status(self):
        pass


class FakeContent:
    def __init__(self, payload):
        self.payload = payload

    async def iter_chunked(self, size):
        assert size > 0
        for offset in range(0, len(self.payload), size):
            yield self.payload[offset : offset + size]


class UnreadableContent:
    async def iter_chunked(self, size):
        raise AssertionError("body must not be read when Content-Length exceeds the limit")
        yield b""  # pragma: no cover


class FakeClientSession:
    responses: ClassVar[dict] = {}
    requested_urls: ClassVar[list[str]] = []
    activity: ClassVar[dict[str, int]] = {"active": 0, "max": 0}
    init_kwargs: ClassVar[dict | None] = None

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        type(self).init_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def get(self, url, proxy=None, allow_redirects=True):
        assert allow_redirects is False
        self.requested_urls.append(url)
        return FakeJsonResponse(self.responses[url], self.activity)


class SequenceResponse:
    def __init__(self, status):
        self.status = status
        self.content_length = None
        self.content = FakeContent(b'{"ok": true}')

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        if self.status >= 400:
            raise ClientResponseError(None, (), status=self.status)


class SequenceSession:
    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self.calls = 0

    def get(self, url, proxy=None, allow_redirects=True):
        assert allow_redirects is False
        self.calls += 1
        return SequenceResponse(next(self.statuses))


class TestSubjectFrequency:
    def test_deduplicates_lessons_and_subjects(self, monkeypatch):
        monkeypatch.setattr(librus_optimizations, "MAX_ATTENDANCE_RECORDS", 3)
        monkeypatch.setattr(librus_optimizations, "MAX_UNIQUE_LESSON_IDS", 2)
        monkeypatch.setattr(librus_optimizations, "MAX_UNIQUE_SUBJECT_IDS", 1)
        base_url = "https://synergia.librus.pl"
        attendances = [
            {"Date": "2026-01-01", "Lesson": {"Id": 1}, "Type": {"Id": 100}},
            {"Date": "2026-01-02", "Lesson": {"Id": 1}, "Type": {"Id": 1}},
            {"Date": "2026-01-03", "Lesson": {"Id": 2}, "Type": {"Id": 100}},
        ]
        FakeClientSession.responses = {
            f"{base_url}/gateway/api/2.0/Lessons/1": {"Lesson": {"Subject": {"Id": 9}}},
            f"{base_url}/gateway/api/2.0/Lessons/2": {"Lesson": {"Subject": {"Id": 9}}},
            f"{base_url}/gateway/api/2.0/Subjects/9": {"Subject": {"Name": "Math"}},
        }
        FakeClientSession.requested_urls = []
        FakeClientSession.activity = {"active": 0, "max": 0}
        client = SimpleNamespace(
            BASE_URL=base_url,
            GATEWAY_API_ATTENDANCE=f"{base_url}/gateway/api/2.0/Attendances",
            proxy={},
            _session=SimpleNamespace(cookies={"DZIENNIKSID": "secret"}, headers={}),
            refresh_oauth=MagicMock(),
            get=MagicMock(return_value=SimpleNamespace(json=lambda: {"Attendances": attendances})),
        )

        with patch.object(librus_optimizations, "ClientSession", FakeClientSession):
            result = librus_optimizations.get_subject_frequency(client)

        assert result == {"Math": 66.67}
        assert len(FakeClientSession.requested_urls) == 3
        assert FakeClientSession.requested_urls.count(f"{base_url}/gateway/api/2.0/Subjects/9") == 1
        assert FakeClientSession.activity["max"] == 2
        cookie_jar = FakeClientSession.init_kwargs["cookie_jar"]
        assert cookie_jar.filter_cookies(URL(base_url))
        assert not cookie_jar.filter_cookies(URL("https://evil.example"))

    @pytest.mark.asyncio
    async def test_redirect_is_not_followed_and_triggers_auth_retry(self):
        session = SequenceSession([302])

        with pytest.raises(AuthorizationError, match="redirect"):
            await librus_optimizations._request_json(
                session, "https://synergia.librus.pl/gateway", asyncio.Semaphore(1), None
            )

        assert session.calls == 1

    @pytest.mark.asyncio
    async def test_client_error_is_not_retried(self):
        session = SequenceSession([404])

        with pytest.raises(ClientResponseError):
            await librus_optimizations._request_json(
                session, "https://synergia.librus.pl/gateway", asyncio.Semaphore(1), None
            )

        assert session.calls == 1

    @pytest.mark.asyncio
    async def test_server_error_retries_within_bound(self):
        session = SequenceSession([500, 200])

        with patch.object(librus_optimizations.asyncio, "sleep", AsyncMock()):
            result = await librus_optimizations._request_json(
                session, "https://synergia.librus.pl/gateway", asyncio.Semaphore(1), None
            )

        assert result == {"ok": True}
        assert session.calls == librus_optimizations.GATEWAY_RETRIES

    @pytest.mark.asyncio
    @pytest.mark.parametrize("content_length", [5, None])
    async def test_gateway_rejects_declared_or_chunked_body_over_limit(
        self, monkeypatch, content_length
    ):
        monkeypatch.setattr(librus_optimizations, "MAX_GATEWAY_RESPONSE_BYTES", 4)
        response = SequenceResponse(200)
        response.content_length = content_length
        response.content = FakeContent(b"12345")
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(RuntimeError, match="gateway response body is too large"):
            await librus_optimizations._request_json(
                session, "https://synergia.librus.pl/gateway", asyncio.Semaphore(1), None
            )

    @pytest.mark.asyncio
    async def test_gateway_accepts_body_at_exact_size_limit(self, monkeypatch):
        monkeypatch.setattr(librus_optimizations, "MAX_GATEWAY_RESPONSE_BYTES", 2)
        response = SequenceResponse(200)
        response.content_length = 2
        response.content = FakeContent(b"{}")
        session = MagicMock()
        session.get.return_value = response

        result = await librus_optimizations._request_json(
            session, "https://synergia.librus.pl/gateway", asyncio.Semaphore(1), None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_declared_oversize_is_rejected_before_reading_body(self, monkeypatch):
        monkeypatch.setattr(librus_optimizations, "MAX_GATEWAY_RESPONSE_BYTES", 2)
        response = SequenceResponse(200)
        response.content_length = 3
        response.content = UnreadableContent()
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(RuntimeError, match="gateway response body is too large"):
            await librus_optimizations._request_json(
                session, "https://synergia.librus.pl/gateway", asyncio.Semaphore(1), None
            )

    @pytest.mark.asyncio
    async def test_declared_body_below_limit_is_read(self, monkeypatch):
        monkeypatch.setattr(librus_optimizations, "MAX_GATEWAY_RESPONSE_BYTES", 3)
        response = SequenceResponse(200)
        response.content_length = 2
        response.content = FakeContent(b"{}")
        session = MagicMock()
        session.get.return_value = response

        result = await librus_optimizations._request_json(
            session, "https://synergia.librus.pl/gateway", asyncio.Semaphore(1), None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_invalid_utf8_gateway_body_is_normalized(self):
        response = SequenceResponse(200)
        response.content = FakeContent(b'\xff{"ok": true}')
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(ParseError, match="gateway response is not valid JSON"):
            await librus_optimizations._request_json(
                session, "https://synergia.librus.pl/gateway", asyncio.Semaphore(1), None
            )

    def test_resolution_deadline_cancels_outstanding_requests(self, monkeypatch):
        cancelled = False

        async def never_finishes(client, attendances):
            nonlocal cancelled
            try:
                await asyncio.Event().wait()
            finally:
                cancelled = True

        client = SimpleNamespace(
            GATEWAY_API_ATTENDANCE="https://synergia.librus.pl/gateway",
            refresh_oauth=MagicMock(),
            get=MagicMock(
                return_value=SimpleNamespace(
                    json=lambda: {
                        "Attendances": [
                            {
                                "Date": "2026-01-01",
                                "Lesson": {"Id": 1},
                                "Type": {"Id": 100},
                            }
                        ]
                    }
                )
            ),
        )
        monkeypatch.setattr(librus_optimizations, "_resolve_subjects", never_finishes)
        monkeypatch.setattr(librus_optimizations, "GATEWAY_RESOLUTION_TIMEOUT_SECONDS", 0.01)

        with pytest.raises(TimeoutError):
            librus_optimizations.get_subject_frequency(client)

        assert cancelled is True

    def test_attendance_record_count_is_bounded_before_task_creation(self, monkeypatch):
        monkeypatch.setattr(librus_optimizations, "MAX_ATTENDANCE_RECORDS", 1)
        client = SimpleNamespace(
            GATEWAY_API_ATTENDANCE="https://synergia.librus.pl/gateway",
            refresh_oauth=MagicMock(),
            get=MagicMock(
                return_value=SimpleNamespace(
                    json=lambda: {
                        "Attendances": [
                            {"Date": "2026-01-01", "Lesson": {"Id": 1}, "Type": {"Id": 100}},
                            {"Date": "2026-01-02", "Lesson": {"Id": 2}, "Type": {"Id": 100}},
                        ]
                    }
                )
            ),
        )

        with pytest.raises(ValueError, match="attendance record count"):
            librus_optimizations.get_subject_frequency(client)

    @pytest.mark.asyncio
    async def test_unique_lesson_count_is_bounded_before_session_creation(self, monkeypatch):
        monkeypatch.setattr(librus_optimizations, "MAX_UNIQUE_LESSON_IDS", 1)
        client = SimpleNamespace()
        attendances = [
            {"Lesson": {"Id": 1}, "Type": {"Id": 100}},
            {"Lesson": {"Id": 2}, "Type": {"Id": 100}},
        ]

        with (
            patch.object(librus_optimizations, "ClientSession") as session,
            pytest.raises(ValueError, match="unique lesson count"),
        ):
            await librus_optimizations._resolve_subjects(client, attendances)

        session.assert_not_called()

    @pytest.mark.asyncio
    async def test_unique_subject_count_is_bounded_before_subject_tasks(self, monkeypatch):
        monkeypatch.setattr(librus_optimizations, "MAX_UNIQUE_SUBJECT_IDS", 1)
        client = SimpleNamespace(
            BASE_URL="https://synergia.librus.pl",
            proxy={},
            _session=SimpleNamespace(cookies={}, headers={}),
        )
        attendances = [
            {"Lesson": {"Id": 1}, "Type": {"Id": 100}},
            {"Lesson": {"Id": 2}, "Type": {"Id": 100}},
        ]
        lesson_payloads = [
            {"Lesson": {"Subject": {"Id": 10}}},
            {"Lesson": {"Subject": {"Id": 20}}},
        ]

        with (
            patch.object(librus_optimizations, "ClientSession", FakeClientSession),
            patch.object(
                librus_optimizations, "_request_json", AsyncMock(side_effect=lesson_payloads)
            ) as request,
            pytest.raises(ValueError, match="unique subject count"),
        ):
            await librus_optimizations._resolve_subjects(client, attendances)

        assert request.await_count == 2

    @pytest.mark.asyncio
    async def test_unique_subject_count_below_limit_is_accepted(self, monkeypatch):
        monkeypatch.setattr(librus_optimizations, "MAX_UNIQUE_SUBJECT_IDS", 2)
        client = SimpleNamespace(
            BASE_URL="https://synergia.librus.pl",
            proxy={},
            _session=SimpleNamespace(cookies={}, headers={}),
        )
        attendances = [{"Lesson": {"Id": 1}, "Type": {"Id": 100}}]
        payloads = [
            {"Lesson": {"Subject": {"Id": 10}}},
            {"Subject": {"Name": "Math"}},
        ]

        with (
            patch.object(librus_optimizations, "ClientSession", FakeClientSession),
            patch.object(
                librus_optimizations, "_request_json", AsyncMock(side_effect=payloads)
            ) as request,
        ):
            result = await librus_optimizations._resolve_subjects(client, attendances)

        assert result == [("Math", "ob")]
        assert request.await_count == 2

    @pytest.mark.asyncio
    async def test_lesson_response_count_must_match_request_count(self):
        client = SimpleNamespace(
            BASE_URL="https://synergia.librus.pl",
            proxy={},
            _session=SimpleNamespace(cookies={}, headers={}),
        )
        attendances = [{"Lesson": {"Id": 1}, "Type": {"Id": 100}}]

        async def drop_responses(*coroutines):
            for coroutine in coroutines:
                coroutine.close()
            return []

        with (
            patch.object(librus_optimizations, "ClientSession", FakeClientSession),
            patch.object(librus_optimizations.asyncio, "gather", drop_responses),
            pytest.raises(ValueError, match=r"zip\(\) argument 2 is shorter"),
        ):
            await librus_optimizations._resolve_subjects(client, attendances)


class TestFirstPageReuse:
    def test_received_messages_parse_page_and_count_from_one_response(self):
        html = '<div class="pagination"><span>1 z 3</span></div>'
        client = SimpleNamespace(
            MESSAGE_URL="https://synergia.librus.pl/wiadomosci",
            get=MagicMock(return_value=SimpleNamespace(text=html)),
        )
        messages = [SimpleNamespace(href="1")]

        with (
            patch.object(librus_optimizations, "no_access_check", side_effect=lambda soup: soup),
            patch.object(librus_optimizations, "parse_messages", return_value=messages),
        ):
            max_page, result = librus_optimizations.get_received_first_page(client)

        assert max_page == 2
        assert result == messages
        client.get.assert_called_once_with(client.MESSAGE_URL)

    def test_completed_lessons_parse_page_and_count_from_one_response(self):
        html = (
            '<div class="pagination"><span>1 z 3</span></div>'
            '<table class="decorated"><tbody><tr></tr><tr></tr></tbody></table>'
        )
        client = SimpleNamespace(
            COMPLETED_LESSONS_URL="https://synergia.librus.pl/zrealizowane",
            post=MagicMock(return_value=SimpleNamespace(text=html)),
        )

        with (
            patch.object(librus_optimizations, "no_access_check", side_effect=lambda soup: soup),
            patch.object(
                librus_optimizations,
                "create_completed_lesson",
                side_effect=["lesson-1", "lesson-2"],
            ),
        ):
            max_page, lessons = librus_optimizations.get_completed_first_page(
                client, "2026-01-01", "2026-01-31"
            )

        assert max_page == 2
        assert lessons == ["lesson-1", "lesson-2"]
        client.post.assert_called_once()


class TestParallelNotifications:
    def test_safe_categories_use_bounded_parallelism(self):
        active = {"count": 0, "max": 0, "started": 0}
        lock = threading.Lock()
        first_wave = threading.Barrier(3, timeout=10)

        def tracked_result(result):
            def run(client, *args):
                with lock:
                    active["count"] += 1
                    active["started"] += 1
                    active["max"] = max(active["max"], active["count"])
                    wait_for_wave = active["started"] <= 3
                if wait_for_wave:
                    first_wave.wait()
                with lock:
                    active["count"] -= 1
                return result

            return run

        client = SimpleNamespace(
            token=object(),
            cookies={},
            _session=SimpleNamespace(),
        )
        seen = NotificationIds([], [], [], [], [], [])
        sessions = [MagicMock() for _ in range(5)]
        session_factory = MagicMock(side_effect=sessions)
        fixed_now = MagicMock()
        fixed_now.date.return_value = date(2026, 9, 9)
        clock = MagicMock()
        clock.now.return_value = fixed_now

        with (
            patch.object(librus_optimizations, "datetime", clock),
            patch.object(librus_optimizations, "get_grades", tracked_result(([], {}, []))),
            patch.object(librus_optimizations, "get_attendance", tracked_result([])),
            patch.object(librus_optimizations, "get_received", tracked_result([])),
            patch.object(librus_optimizations, "get_announcements", tracked_result([])),
            patch.object(librus_optimizations, "get_homework", tracked_result([])),
            patch.object(librus_optimizations, "get_recently_added_schedule", return_value=[]),
        ):
            data, updated = librus_optimizations.get_new_notifications(
                client, seen, session_factory
            )

        assert active["max"] == librus_optimizations.NOTIFICATION_CONCURRENCY
        clock.now.assert_called_once_with(librus_optimizations.SCHOOL_TIME_ZONE)
        assert session_factory.call_count == 5
        assert len({id(session) for session in sessions}) == 5
        for session in sessions:
            session.close.assert_called_once()
        assert data.grades == []
        assert updated.grades == []


class TestRecoverableScheduleNotifications:
    def test_standalone_fetch_checkpoints_before_returning(self, monkeypatch):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        checkpoint = MagicMock()
        monkeypatch.setattr(librus_optimizations, "MAX_SCHEDULE_EVENTS_PER_CALL", 1)

        with patch.object(
            librus_optimizations, "get_recently_added_schedule", return_value=[event]
        ):
            events, seen_ids = librus_optimizations.get_recent_schedule_events(
                SimpleNamespace(), [], [], checkpoint
            )

        checkpoint.assert_called_once_with([event])
        assert events == [event]
        assert seen_ids == [schedule_event_id(event)]

    def test_schedule_overflow_is_checkpointed_before_rejection(self, monkeypatch):
        events = [
            RecentEvent(f"2026-09-15 0{index}:00", "Sprawdzian", f"Event {index}")
            for index in range(2)
        ]
        checkpoint = MagicMock()
        monkeypatch.setattr(librus_optimizations, "MAX_SCHEDULE_EVENTS_PER_CALL", 1)

        with (
            patch.object(librus_optimizations, "get_recently_added_schedule", return_value=events),
            pytest.raises(ValueError, match="preserved"),
        ):
            librus_optimizations.get_recent_schedule_events(SimpleNamespace(), [], [], checkpoint)

        checkpoint.assert_called_once_with(events)

    def test_pending_event_is_reported_even_when_legacy_id_was_saved(self):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        legacy_id = hashlib.md5(event.data.encode(), usedforsecurity=False).hexdigest()

        events, seen_ids = librus_optimizations._parse_schedule_notifications(
            [event], [], [legacy_id]
        )

        assert events == [event]
        assert schedule_event_id(event) in seen_ids

    def test_pending_events_drain_before_consuming_upstream_again(self):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        checkpoint = MagicMock()

        with patch.object(librus_optimizations, "get_recently_added_schedule") as upstream:
            events, seen_ids = librus_optimizations.get_recent_schedule_events(
                SimpleNamespace(), [], [event], checkpoint
            )

        upstream.assert_not_called()
        checkpoint.assert_called_once_with([])
        assert events == [event]
        assert seen_ids == [schedule_event_id(event)]

    def test_aggregate_notifications_drain_pending_schedule_before_upstream(self):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        seen = NotificationIds([], [], [], [], [], [])
        sessions = [MagicMock() for _ in range(5)]
        checkpoint = MagicMock()
        client = SimpleNamespace(token=object(), cookies={}, _session=SimpleNamespace())

        with (
            patch.object(librus_optimizations, "get_grades", return_value=([], {}, [])),
            patch.object(librus_optimizations, "get_attendance", return_value=[]),
            patch.object(librus_optimizations, "get_received", return_value=[]),
            patch.object(librus_optimizations, "get_announcements", return_value=[]),
            patch.object(librus_optimizations, "get_homework", return_value=[]),
            patch.object(librus_optimizations, "get_recently_added_schedule") as upstream,
        ):
            data, updated = librus_optimizations.get_new_notifications(
                client,
                seen,
                MagicMock(side_effect=sessions),
                pending_schedule=[event],
                schedule_checkpoint=checkpoint,
            )

        upstream.assert_not_called()
        checkpoint.assert_called_once_with([])
        assert data.schedule == [event]
        assert updated.schedule == [schedule_event_id(event)]

    def test_fresh_event_seen_only_under_legacy_id_is_replayed_once(self):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        legacy_id = hashlib.md5(event.data.encode(), usedforsecurity=False).hexdigest()

        events, seen_ids = librus_optimizations._parse_schedule_notifications(
            [], [event], [legacy_id]
        )

        assert events == [event]
        assert schedule_event_id(event) in seen_ids

        events, _ = librus_optimizations._parse_schedule_notifications([], [event], seen_ids)
        assert events == []

    def test_pending_and_fresh_copy_are_returned_once(self):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")

        events, seen_ids = librus_optimizations._parse_schedule_notifications([event], [event], [])

        assert events == [event]
        assert seen_ids == [schedule_event_id(event)]
