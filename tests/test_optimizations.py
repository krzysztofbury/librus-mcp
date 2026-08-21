import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientResponseError
from librus_apix.exceptions import AuthorizationError
from librus_apix.notifications import NotificationIds
from yarl import URL

from src import librus_optimizations


class FakeJsonResponse:
    status = 200

    def __init__(self, payload, activity):
        self.payload = payload
        self.activity = activity

    async def __aenter__(self):
        self.activity["active"] += 1
        self.activity["max"] = max(self.activity["max"], self.activity["active"])
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *args):
        self.activity["active"] -= 1

    def raise_for_status(self):
        pass

    async def json(self):
        return self.payload


class FakeClientSession:
    responses = {}
    requested_urls = []
    activity = {"active": 0, "max": 0}
    init_kwargs = None

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

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        if self.status >= 400:
            raise ClientResponseError(None, (), status=self.status)

    async def json(self):
        return {"ok": True}


class SequenceSession:
    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self.calls = 0

    def get(self, url, proxy=None, allow_redirects=True):
        assert allow_redirects is False
        self.calls += 1
        return SequenceResponse(next(self.statuses))


class TestSubjectFrequency:
    def test_deduplicates_lessons_and_subjects(self):
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

        with (
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
        assert session_factory.call_count == 5
        assert len({id(session) for session in sessions}) == 5
        for session in sessions:
            session.close.assert_called_once()
        assert data.grades == []
        assert updated.grades == []
