"""Tests for LibrusManager session safety: cookie isolation, per-alias
serialization, auth retry, error normalization, and bounded all-pages fetch."""

import asyncio
import dataclasses
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from librus_apix.exceptions import MaintananceError, ParseError, TokenError

import src.librus_client as librus_client_module
from src.librus_client import LibrusManager


@dataclasses.dataclass
class FakeMessage:
    href: str


def _messages(page: int, count: int) -> list[FakeMessage]:
    return [FakeMessage(href=f"p{page}m{index}") for index in range(count)]


class TestCookieIsolation:
    @pytest.mark.asyncio
    async def test_clients_get_distinct_cookie_jars(self, monkeypatch):
        """Upstream new_client() shares one mutable default jar between all
        clients; a request for one child must never carry another child's
        session cookies."""
        monkeypatch.setenv(
            "LIBRUS_ACCOUNTS",
            json.dumps(
                [
                    {
                        "alias": "first",
                        "username": "u1",
                        "password": "p1",  # pragma: allowlist secret
                    },
                    {
                        "alias": "second",
                        "username": "u2",
                        "password": "p2",  # pragma: allowlist secret
                    },
                ]
            ),
        )
        with patch("src.librus_client.asyncio.to_thread", new_callable=AsyncMock) as to_thread:
            to_thread.return_value = object()  # fake token
            client_first = await LibrusManager.get_client("first")
            client_second = await LibrusManager.get_client("second")
        assert client_first.cookies is not client_second.cookies


class TestExecuteRetry:
    @pytest.mark.asyncio
    async def test_token_error_triggers_single_reauth(self):
        """TokenError ("Brak dostępu" page) must re-authenticate once, exactly
        like AuthorizationError and TokenKeyError."""
        calls = {"count": 0}

        def flaky(client):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TokenError("Brak dostępu")
            return "ok"

        with patch.object(LibrusManager, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = object()
            result = await LibrusManager._execute("test_student", flaky)
        assert result == "ok"
        assert calls["count"] == 2
        assert get_client.await_count == 2

    @pytest.mark.asyncio
    async def test_second_failure_propagates(self):
        def always_failing(client):
            raise TokenError("Brak dostępu")

        with patch.object(LibrusManager, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = object()
            with pytest.raises(TokenError):
                await LibrusManager._execute("test_student", always_failing)

    @pytest.mark.asyncio
    async def test_non_idempotent_call_is_not_retried(self):
        calls = {"count": 0}

        def token_failure(client):
            calls["count"] += 1
            raise TokenError("Brak dostępu")

        with patch.object(LibrusManager, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = object()
            with pytest.raises(TokenError):
                await LibrusManager._execute(
                    "test_student", token_failure, retry_auth_on_failure=False
                )
        assert calls["count"] == 1
        assert get_client.await_count == 1

    @pytest.mark.asyncio
    async def test_send_disables_auth_retry(self):
        with patch.object(
            LibrusManager,
            "_execute",
            new_callable=AsyncMock,
            side_effect=TokenError("Brak dostępu"),
        ) as execute:
            with pytest.raises(RuntimeError, match="not retried"):
                await LibrusManager.send_message_to("test_student", "Subject", "Body", ["1"])
        assert execute.await_args.kwargs["retry_auth_on_failure"] is False

    @pytest.mark.asyncio
    async def test_send_timeout_reports_an_uncertain_delivery(self):
        with patch.object(
            LibrusManager, "_execute", new_callable=AsyncMock, side_effect=TimeoutError()
        ):
            with pytest.raises(RuntimeError, match="delivery is uncertain"):
                await LibrusManager.send_message_to("test_student", "Subject", "Body", ["1"])

    @pytest.mark.asyncio
    async def test_send_cancellation_reports_an_uncertain_delivery(self):
        with patch.object(
            LibrusManager,
            "_execute",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError(),
        ):
            with pytest.raises(RuntimeError, match="delivery is uncertain"):
                await LibrusManager.send_message_to("test_student", "Subject", "Body", ["1"])

    @pytest.mark.asyncio
    async def test_maintenance_error_is_actionable(self):
        def maintenance(client):
            raise MaintananceError("prace serwisowe")

        with patch.object(LibrusManager, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = object()
            with pytest.raises(RuntimeError, match="maintenance"):
                await LibrusManager._execute("test_student", maintenance)

    @pytest.mark.asyncio
    async def test_parse_error_is_actionable(self):
        def unparseable(client):
            raise ParseError("layout drift")

        with patch.object(LibrusManager, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = object()
            with pytest.raises(RuntimeError, match="librus-apix"):
                await LibrusManager._execute("test_student", unparseable)


class TestUpstreamTimeouts:
    def test_session_applies_default_request_timeout(self):
        session = librus_client_module.LibrusTimeoutSession()
        with patch("requests.Session.request", return_value=MagicMock()) as request:
            session.get("https://example.invalid")
        session.close()
        assert (
            request.call_args.kwargs["timeout"]
            == librus_client_module.UPSTREAM_REQUEST_TIMEOUT_SECONDS
        )

    @pytest.mark.asyncio
    async def test_operation_timeout_evicts_the_client(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "UPSTREAM_OPERATION_TIMEOUT_SECONDS", 0.01)
        client = object()
        LibrusManager._instances["test_student"] = client

        def slow_call(received_client):
            assert received_client is client
            import time

            time.sleep(0.1)

        with patch.object(LibrusManager, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = client
            with pytest.raises(TimeoutError, match="timed out"):
                await LibrusManager._execute("test_student", slow_call)
            with pytest.raises(RuntimeError, match="still completing"):
                await LibrusManager._execute("test_student", lambda _: "unexpected")
            await asyncio.sleep(0.15)
            assert await LibrusManager._execute("test_student", lambda _: "ok") == "ok"
        assert "test_student" not in LibrusManager._instances

    @pytest.mark.asyncio
    async def test_login_timeout_does_not_start_an_auth_cooldown(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "UPSTREAM_OPERATION_TIMEOUT_SECONDS", 0.01)

        async def slow_login(*args, **kwargs):
            await asyncio.sleep(0.1)

        with patch("src.librus_client.asyncio.to_thread", side_effect=slow_login):
            with pytest.raises(TimeoutError, match="authentication timed out"):
                await LibrusManager.get_client("test_student")
        assert LibrusManager._auth_cooldowns == {}

    @pytest.mark.asyncio
    async def test_login_timeout_quarantines_the_alias(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "UPSTREAM_OPERATION_TIMEOUT_SECONDS", 0.01)

        class SlowClient:
            def __init__(self):
                self._session = MagicMock()
                self.cookies = None

            def get_token(self, username, password):
                import time

                time.sleep(0.1)
                return object()

        with patch("src.librus_client.new_client", return_value=SlowClient()):
            with pytest.raises(TimeoutError, match="authentication timed out"):
                await LibrusManager.get_client("test_student")
            with pytest.raises(RuntimeError, match="still completing"):
                await LibrusManager.get_client("test_student")
            await asyncio.sleep(0.15)
        assert LibrusManager._timed_out_workers == {}


class TestAuthCooldown:
    @pytest.mark.asyncio
    async def test_throttled_login_gets_actionable_error_and_cooldown(self):
        """A non-JSON login response (Librus throttling) must produce a
        throttle-specific error, and the very next attempt must fail fast
        without touching the login endpoint again."""
        from requests.exceptions import JSONDecodeError

        with patch("src.librus_client.asyncio.to_thread", new_callable=AsyncMock) as to_thread:
            to_thread.side_effect = JSONDecodeError("Expecting value", "", 0)
            with pytest.raises(ValueError, match="login throttling"):
                await LibrusManager.get_client("test_student")
            with pytest.raises(ValueError, match="cooldown"):
                await LibrusManager.get_client("test_student")
            assert to_thread.await_count == 1

    @pytest.mark.asyncio
    async def test_any_auth_failure_starts_cooldown(self):
        from librus_apix.exceptions import AuthorizationError

        with patch("src.librus_client.asyncio.to_thread", new_callable=AsyncMock) as to_thread:
            to_thread.side_effect = AuthorizationError("bad credentials")
            with pytest.raises(ValueError, match="Failed to authenticate"):
                await LibrusManager.get_client("test_student")
            with pytest.raises(ValueError, match="cooldown"):
                await LibrusManager.get_client("test_student")
            assert to_thread.await_count == 1

    @pytest.mark.asyncio
    async def test_expired_cooldown_allows_retry_and_success_clears_it(self, monkeypatch):
        from librus_apix.exceptions import AuthorizationError

        monkeypatch.setattr(librus_client_module, "AUTH_COOLDOWN_SECONDS", 0.0)
        with patch("src.librus_client.asyncio.to_thread", new_callable=AsyncMock) as to_thread:
            to_thread.side_effect = [AuthorizationError("flaky"), object()]
            with pytest.raises(ValueError, match="Failed to authenticate"):
                await LibrusManager.get_client("test_student")
            client = await LibrusManager.get_client("test_student")
            assert client is not None
            assert to_thread.await_count == 2
        assert LibrusManager._auth_cooldowns == {}

    @pytest.mark.asyncio
    async def test_cooldown_error_repeats_original_reason(self):
        from librus_apix.exceptions import AuthorizationError

        with patch("src.librus_client.asyncio.to_thread", new_callable=AsyncMock) as to_thread:
            to_thread.side_effect = AuthorizationError("bad credentials")
            with pytest.raises(ValueError):
                await LibrusManager.get_client("test_student")
            with pytest.raises(ValueError, match="bad credentials"):
                await LibrusManager.get_client("test_student")


class TestAttendanceFrequency:
    @pytest.mark.asyncio
    async def test_custom_attendance_type_yields_actionable_error(self):
        """Schools can define attendance types missing from upstream's
        hardcoded gateway map (seen live: ID 4766); the raw KeyError must
        become an error that points at the working alternative."""
        mock = AsyncMock(side_effect=KeyError("4766"))
        with patch.object(LibrusManager, "_execute", mock):
            with pytest.raises(RuntimeError, match="get_subject_frequency"):
                await LibrusManager.fetch_attendance_frequency("test_student")


class TestUnknownAlias:
    @pytest.mark.asyncio
    async def test_unknown_alias_raises_and_creates_no_locks(self):
        with pytest.raises(ValueError, match="not found"):
            await LibrusManager._execute("ghost", lambda client: None)
        assert "ghost" not in LibrusManager._client_locks
        assert "ghost" not in LibrusManager._notification_locks

    @pytest.mark.asyncio
    async def test_unknown_alias_lists_configured(self):
        with pytest.raises(ValueError, match="test_student"):
            await LibrusManager.fetch_grades("ghost")


class TestPerAliasSerialization:
    @pytest.mark.asyncio
    async def test_same_alias_requests_are_serialized(self):
        """Two concurrent calls for one alias must not overlap: the client's
        session and cookie jar are not thread-safe."""
        active = {"count": 0, "max": 0}

        def tracked(client):
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
            # Yield the GIL long enough for overlap to show if the lock fails.
            import time

            time.sleep(0.02)
            active["count"] -= 1
            return "ok"

        with patch.object(LibrusManager, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = object()
            await asyncio.gather(
                LibrusManager._execute("test_student", tracked),
                LibrusManager._execute("test_student", tracked),
            )
        assert active["max"] == 1


class TestNotificationStateLock:
    @pytest.mark.asyncio
    async def test_cancelled_lock_wait_does_not_acquire_a_descriptor(self, monkeypatch, tmp_path):
        monkeypatch.setattr(librus_client_module, "NOTIFICATION_LOCK_MAX_ATTEMPTS", 100)
        monkeypatch.setattr(
            librus_client_module, "try_acquire_notification_state_lock", lambda *_: None
        )
        task = asyncio.create_task(
            LibrusManager._acquire_notification_state_lock(tmp_path, "test_student")
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestFetchAllMessages:
    @pytest.mark.asyncio
    async def test_received_fetches_every_page(self):
        mock = AsyncMock()
        mock.side_effect = [1, _messages(0, 50), _messages(1, 7)]
        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "received")
        assert len(result["messages"]) == 57
        assert result["pages_fetched"] == 2
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_received_truncates_at_page_cap(self, monkeypatch):
        monkeypatch.setattr(librus_client_module.LibrusManager, "_execute", AsyncMock())
        monkeypatch.setattr(librus_client_module, "MAX_ALL_MESSAGE_PAGES", 2)
        mock = librus_client_module.LibrusManager._execute
        mock.side_effect = [5, _messages(0, 50), _messages(1, 50)]
        result = await LibrusManager.fetch_all_messages("test_student", "received")
        assert result["pages_fetched"] == 2
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_sent_stops_on_short_page(self):
        mock = AsyncMock()
        mock.side_effect = [_messages(0, 50), _messages(1, 3)]
        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "sent")
        assert len(result["messages"]) == 53
        assert result["pages_fetched"] == 2
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_sent_stops_on_repeated_page(self):
        """Librus clamps out-of-range pages to the last page; an identical
        page must terminate the loop instead of duplicating messages."""
        full_page = _messages(0, 50)
        mock = AsyncMock()
        mock.side_effect = [full_page, list(full_page)]
        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "sent")
        assert len(result["messages"]) == 50
        assert result["pages_fetched"] == 1
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_sent_truncates_at_page_cap(self, monkeypatch):
        monkeypatch.setattr(librus_client_module.LibrusManager, "_execute", AsyncMock())
        monkeypatch.setattr(librus_client_module, "MAX_ALL_MESSAGE_PAGES", 2)
        mock = librus_client_module.LibrusManager._execute
        mock.side_effect = [_messages(0, 50), _messages(1, 50)]
        result = await LibrusManager.fetch_all_messages("test_student", "sent")
        assert result["pages_fetched"] == 2
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_invalid_folder_raises(self):
        with pytest.raises(ValueError, match="folder"):
            await LibrusManager.fetch_all_messages("test_student", "archive")


class TestScheduleDetailValidation:
    @pytest.mark.asyncio
    async def test_valid_href_splits_prefix_and_suffix(self):
        mock = AsyncMock(return_value={"Data": "2026-06-01"})
        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_schedule_detail("test_student", "szczegoly/12345")
        assert result == {"Data": "2026-06-01"}
        call_args = mock.call_args.args
        assert call_args[2] == "szczegoly"
        assert call_args[3] == "12345"

    @pytest.mark.asyncio
    async def test_malformed_href_raises(self):
        with pytest.raises(ValueError, match="href"):
            await LibrusManager.fetch_schedule_detail("test_student", "https://evil.example/x")
