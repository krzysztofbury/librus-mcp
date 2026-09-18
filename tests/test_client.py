"""Tests for LibrusManager session safety: cookie isolation, per-alias
serialization, auth retry, error normalization, and bounded all-pages fetch."""

import asyncio
import dataclasses
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from librus_apix.exceptions import (
    AuthorizationError,
    MaintananceError,
    ParseError,
    TokenError,
    TokenKeyError,
)
from librus_apix.grades import get_grades
from requests import Request

import src.librus_client as librus_client_module
from src.librus_client import LibrusManager


@dataclasses.dataclass
class FakeMessage:
    href: str


def _messages(page: int, count: int) -> list[FakeMessage]:
    return [FakeMessage(href=f"p{page}m{index}") for index in range(count)]


class _KeepAliveHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


class _RedirectBodyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    final_requests = 0

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Content-Length", "5")
            self.send_header("Location", "/middle")
            self.end_headers()
            self.wfile.write(b"12345")
            return
        if self.path == "/middle":
            self.send_response(302)
            self.send_header("Content-Length", "3")
            self.send_header("Location", "/final")
            self.end_headers()
            self.wfile.write(b"mid")
            return
        type(self).final_requests += 1
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


class _ConnectionCountingServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.connection_count = 0
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, address = super().get_request()
        self.connection_count += 1
        return request, address


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
    @pytest.mark.parametrize("error_type", [AuthorizationError, TokenError, TokenKeyError])
    async def test_second_auth_failure_evicts_fresh_client_and_starts_cooldown(self, error_type):
        clients = [MagicMock(), MagicMock()]
        available_clients = iter(clients)

        async def cache_next_client(alias):
            client = next(available_clients)
            LibrusManager._instances[alias] = client
            LibrusManager._tokens[alias] = object()
            return client

        def always_failing(client):
            raise error_type("Brak dostępu")

        with (
            patch.object(
                LibrusManager, "get_client", new_callable=AsyncMock, side_effect=cache_next_client
            ) as get_client,
            pytest.raises(PermissionError, match="persistently denied"),
        ):
            await LibrusManager._execute("test_student", always_failing)

        assert get_client.await_count == 2
        assert LibrusManager._instances == {}
        assert LibrusManager._tokens == {}
        assert LibrusManager._operation_auth_cooldowns
        for client in clients:
            client._session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_persistent_denial_cooldown_bounds_logins_and_is_scoped(self, monkeypatch):
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
        clients = [MagicMock() for _ in range(5)]
        available_clients = iter(clients)
        denied_attempts = 0

        async def cache_next_client(alias):
            client = next(available_clients)
            LibrusManager._instances[alias] = client
            LibrusManager._tokens[alias] = object()
            return client

        def denied(client):
            nonlocal denied_attempts
            denied_attempts += 1
            raise TokenError("Brak dostępu")

        with patch.object(
            LibrusManager, "get_client", new_callable=AsyncMock, side_effect=cache_next_client
        ) as get_client:
            with pytest.raises(PermissionError, match="persistently denied"):
                await LibrusManager._execute("first", denied)
            for _ in range(5):
                with pytest.raises(PermissionError, match="cooldown"):
                    await LibrusManager._execute("first", denied)

            assert await LibrusManager._execute("first", lambda client: "ok") == "ok"
            with pytest.raises(PermissionError, match="persistently denied"):
                await LibrusManager._execute("second", denied)

        assert denied_attempts == 4
        assert get_client.await_count == 5
        for client in (clients[0], clients[1], clients[3], clients[4]):
            client._session.close.assert_called_once()
        clients[2]._session.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_expired_operation_cooldown_allows_one_new_bounded_attempt(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "OPERATION_AUTH_COOLDOWN_SECONDS", 0.0)
        clients = [MagicMock() for _ in range(4)]
        available_clients = iter(clients)
        denied_attempts = 0

        async def cache_next_client(alias):
            client = next(available_clients)
            LibrusManager._instances[alias] = client
            LibrusManager._tokens[alias] = object()
            return client

        def denied(client):
            nonlocal denied_attempts
            denied_attempts += 1
            raise TokenError("Brak dostępu")

        with patch.object(
            LibrusManager, "get_client", new_callable=AsyncMock, side_effect=cache_next_client
        ) as get_client:
            for _ in range(2):
                with pytest.raises(PermissionError, match="persistently denied"):
                    await LibrusManager._execute("test_student", denied)

        assert denied_attempts == 4
        assert get_client.await_count == 4
        for client in clients:
            client._session.close.assert_called_once()

    def test_operation_cooldown_expires_at_deadline_but_not_before(self, monkeypatch):
        operation = "src.librus_client.LibrusManager.fetch_grades"
        key = ("test_student", operation)
        LibrusManager._operation_auth_cooldowns[key] = (100.5, "denied")
        monkeypatch.setattr(librus_client_module.time, "monotonic", lambda: 100.0)

        with pytest.raises(PermissionError, match="cooldown"):
            LibrusManager._check_operation_auth_cooldown(*key)

        LibrusManager._operation_auth_cooldowns[key] = (100.0, "denied")
        LibrusManager._check_operation_auth_cooldown(*key)
        assert key not in LibrusManager._operation_auth_cooldowns

    def test_operation_name_is_stable_and_module_qualified(self):
        assert LibrusManager._operation_name(get_grades) == "librus_apix.grades.get_grades"

    def test_operation_cooldown_policy_values_and_deadline(self, monkeypatch):
        monkeypatch.setattr(librus_client_module.time, "monotonic", lambda: 100.0)

        LibrusManager._start_operation_auth_cooldown("test_student", "operation", "denied")

        assert librus_client_module.AUTH_COOLDOWN_SECONDS == 60.0
        assert librus_client_module.OPERATION_AUTH_COOLDOWN_SECONDS == 60.0
        assert librus_client_module.MAX_PERSISTENT_DENIALS_PER_ALIAS == 3
        assert LibrusManager._operation_auth_cooldowns[("test_student", "operation")][0] == 160.0

    def test_alias_budget_counts_only_active_denials_for_same_alias(self, monkeypatch):
        monkeypatch.setattr(librus_client_module.time, "monotonic", lambda: 100.0)
        LibrusManager._operation_auth_cooldowns.update(
            {
                ("test_student", "expired-one"): (99.0, "denied"),
                ("test_student", "expired-two"): (99.0, "denied"),
                ("test_student", "deadline-one"): (100.0, "denied"),
                ("test_student", "deadline-two"): (100.0, "denied"),
                ("a-other-one", "active"): (200.0, "denied"),
                ("a-other-two", "active"): (200.0, "denied"),
                ("z-other-one", "active"): (200.0, "denied"),
                ("z-other-two", "active"): (200.0, "denied"),
            }
        )

        LibrusManager._start_operation_auth_cooldown("test_student", "new", "denied")

        assert LibrusManager._auth_cooldowns == {}

    def test_alias_budget_uses_value_equality(self, monkeypatch):
        monkeypatch.setattr(librus_client_module.time, "monotonic", lambda: 100.0)
        alias = "test_student"
        equal_alias_one = "".join(("test", "_student"))
        equal_alias_two = "".join(("test_", "student"))
        assert equal_alias_one == alias
        assert equal_alias_one is not alias
        assert equal_alias_two == alias
        assert equal_alias_two is not alias
        LibrusManager._operation_auth_cooldowns.update(
            {
                (equal_alias_one, "denied-one"): (200.0, "denied"),
                (equal_alias_two, "denied-two"): (200.0, "denied"),
            }
        )

        LibrusManager._start_operation_auth_cooldown(alias, "denied-three", "denied")

        assert LibrusManager._auth_cooldowns

    def test_alias_budget_fails_safe_above_threshold(self, monkeypatch):
        monkeypatch.setattr(librus_client_module.time, "monotonic", lambda: 100.0)
        LibrusManager._operation_auth_cooldowns.update(
            {
                ("test_student", "denied-one"): (200.0, "denied"),
                ("test_student", "denied-two"): (200.0, "denied"),
                ("test_student", "denied-three"): (200.0, "denied"),
            }
        )

        LibrusManager._start_operation_auth_cooldown("test_student", "denied-four", "denied")

        assert LibrusManager._auth_cooldowns

    @pytest.mark.asyncio
    async def test_denials_across_operations_start_alias_cooldown(self):
        clients = [MagicMock() for _ in range(6)]
        available_clients = iter(clients)

        async def cache_next_client(alias):
            client = next(available_clients)
            LibrusManager._instances[alias] = client
            LibrusManager._tokens[alias] = object()
            return client

        def denied_one(client):
            raise TokenError("Brak dostępu")

        def denied_two(client):
            raise TokenError("Brak dostępu")

        def denied_three(client):
            raise TokenError("Brak dostępu")

        with patch.object(
            LibrusManager, "get_client", new_callable=AsyncMock, side_effect=cache_next_client
        ) as get_client:
            for operation in (denied_one, denied_two, denied_three):
                with pytest.raises(PermissionError, match="persistently denied"):
                    await LibrusManager._execute("test_student", operation)
            with pytest.raises(ValueError, match="cooldown"):
                await LibrusManager._execute("test_student", lambda client: "healthy")

        assert get_client.await_count == 6
        assert LibrusManager._auth_cooldowns

    @pytest.mark.asyncio
    async def test_close_failure_does_not_bypass_persistent_denial_cooldown(self, capsys):
        clients = [MagicMock(), MagicMock()]
        clients[1]._session.close.side_effect = RuntimeError("close failed")
        available_clients = iter(clients)

        async def cache_next_client(alias):
            client = next(available_clients)
            LibrusManager._instances[alias] = client
            LibrusManager._tokens[alias] = object()
            return client

        def denied(client):
            raise TokenError("Brak dostępu")

        with (
            patch.object(
                LibrusManager, "get_client", new_callable=AsyncMock, side_effect=cache_next_client
            ),
            pytest.raises(PermissionError, match="persistently denied"),
        ):
            await LibrusManager._execute("test_student", denied)

        assert LibrusManager._operation_auth_cooldowns
        assert "cleanup failed (RuntimeError)" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_non_idempotent_call_is_not_retried(self):
        calls = {"count": 0}
        client = MagicMock()
        LibrusManager._instances["test_student"] = client
        LibrusManager._tokens["test_student"] = object()

        def token_failure(client):
            calls["count"] += 1
            raise TokenError("Brak dostępu")

        with patch.object(LibrusManager, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = client
            with pytest.raises(TokenError):
                await LibrusManager._execute(
                    "test_student", token_failure, retry_auth_on_failure=False
                )
        assert calls["count"] == 1
        assert get_client.await_count == 1
        assert LibrusManager._instances == {}
        assert LibrusManager._tokens == {}
        assert LibrusManager._operation_auth_cooldowns == {}
        client._session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_disables_auth_retry(self):
        with (
            patch.object(
                LibrusManager,
                "_execute",
                new_callable=AsyncMock,
                side_effect=TokenError("Brak dostępu"),
            ) as execute,
            pytest.raises(RuntimeError, match="not retried"),
        ):
            await LibrusManager.send_message_to("test_student", "Subject", "Body", ["1"])
        assert execute.await_args.kwargs["retry_auth_on_failure"] is False

    @pytest.mark.asyncio
    async def test_send_timeout_reports_an_uncertain_delivery(self):
        with (
            patch.object(
                LibrusManager, "_execute", new_callable=AsyncMock, side_effect=TimeoutError()
            ),
            pytest.raises(RuntimeError, match="delivery is uncertain"),
        ):
            await LibrusManager.send_message_to("test_student", "Subject", "Body", ["1"])

    @pytest.mark.asyncio
    async def test_send_cancellation_reports_an_uncertain_delivery(self):
        with (
            patch.object(
                LibrusManager,
                "_execute",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError(),
            ),
            pytest.raises(RuntimeError, match="delivery is uncertain"),
        ):
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
    @pytest.mark.asyncio
    async def test_blocked_response_abort_does_not_block_event_loop(self):
        cancellation = librus_client_module.scraping.DownloadCancellation()
        abort_started = threading.Event()
        release_abort = threading.Event()

        def blocking_abort():
            abort_started.set()
            assert release_abort.wait(timeout=5)

        cancellation.set_abort(blocking_abort)
        try:
            await asyncio.wait_for(LibrusManager._cancel_worker(cancellation), timeout=0.1)
            assert abort_started.wait(timeout=5)
        finally:
            release_abort.set()

    @pytest.mark.asyncio
    async def test_publication_barrier_does_not_block_event_loop(self):
        cancellation = librus_client_module.scraping.DownloadCancellation()
        publication_started = threading.Event()
        release_publication = threading.Event()

        def hold_publication_lock():
            with cancellation._publication_lock:
                publication_started.set()
                assert release_publication.wait(timeout=5)

        publisher = threading.Thread(target=hold_publication_lock)
        publisher.start()
        assert publication_started.wait(timeout=5)
        task = asyncio.create_task(LibrusManager._cancel_worker(cancellation))
        try:
            await asyncio.sleep(0)
            assert cancellation._cancelled.is_set()
            assert not task.done()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release_publication.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        publisher.join(timeout=5)
        assert not publisher.is_alive()

    def test_session_context_keeps_connection_pool_open(self):
        session = librus_client_module.LibrusTimeoutSession()
        assert session.max_redirects == librus_client_module.MAX_UPSTREAM_REDIRECTS
        with patch("requests.Session.close") as close:
            with session:
                pass
            close.assert_not_called()
            session.close()
        close.assert_called_once()

    def test_consecutive_requests_reuse_one_http_connection(self):
        server = _ConnectionCountingServer(("127.0.0.1", 0), _KeepAliveHandler)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()
        session = librus_client_module.LibrusTimeoutSession()
        try:
            url = f"http://127.0.0.1:{server.server_port}/"
            for _ in range(2):
                with session as persistent_session:
                    assert persistent_session.get(url).content == b"ok"
            assert server.connection_count == 1
        finally:
            session.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_session_applies_default_request_timeout(self):
        response = MagicMock(status_code=200, headers={"Content-Length": "2"})
        response.iter_content.return_value = [b"ok"]
        session = librus_client_module.LibrusTimeoutSession()
        with patch("requests.Session.request", return_value=response) as request:
            session.get("https://example.invalid")
        session.close()
        assert (
            request.call_args.kwargs["timeout"]
            == librus_client_module.UPSTREAM_REQUEST_TIMEOUT_SECONDS
        )
        assert request.call_args.kwargs["stream"] is True

    def test_session_accepts_body_at_exact_size_limit(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_UPSTREAM_RESPONSE_BYTES", 4)
        response = MagicMock(status_code=200, headers={"Content-Length": "4"})
        response.is_redirect = False
        response.iter_content.return_value = [b"ab", b"cd"]
        session = librus_client_module.LibrusTimeoutSession()

        with patch("requests.Session.send", return_value=response) as send:
            result = session.get("https://example.invalid")

        assert result._content == b"abcd"
        assert result._content_consumed is True
        assert send.call_args.kwargs["stream"] is True
        response.close.assert_not_called()

    @pytest.mark.parametrize("headers", [{"Content-Length": "5"}, {}])
    def test_session_rejects_declared_or_chunked_body_over_limit(self, monkeypatch, headers):
        monkeypatch.setattr(librus_client_module, "MAX_UPSTREAM_RESPONSE_BYTES", 4)
        response = MagicMock(status_code=200, headers=headers)
        response.iter_content.return_value = [b"ab", b"cde"]
        session = librus_client_module.LibrusTimeoutSession()

        with (
            patch("requests.Session.send", return_value=response),
            pytest.raises(RuntimeError, match="response body is too large"),
        ):
            session.get("https://example.invalid")

        response.close.assert_called_once()

    def test_session_bounds_redirect_body_before_following_it(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_UPSTREAM_RESPONSE_BYTES", 4)
        _RedirectBodyHandler.final_requests = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectBodyHandler)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()
        session = librus_client_module.LibrusTimeoutSession()
        try:
            with pytest.raises(RuntimeError, match="response body is too large"):
                session.get(f"http://127.0.0.1:{server.server_port}/redirect")
            assert _RedirectBodyHandler.final_requests == 0
        finally:
            session.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_session_follows_bounded_redirect_by_default(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_UPSTREAM_RESPONSE_BYTES", 5)
        monkeypatch.setattr(librus_client_module, "MAX_UPSTREAM_RESPONSE_CHAIN_BYTES", 10)
        _RedirectBodyHandler.final_requests = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectBodyHandler)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()
        session = librus_client_module.LibrusTimeoutSession()
        try:
            request = Request("GET", f"http://127.0.0.1:{server.server_port}/redirect").prepare()
            response = session.send(request)
            assert response.content == b"ok"
            assert [item.content for item in response.history] == [b"12345", b"mid"]
            assert _RedirectBodyHandler.final_requests == 1
            assert not hasattr(session._response_budget, "remaining_bytes")
        finally:
            session.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_session_respects_disabled_redirects(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_UPSTREAM_RESPONSE_BYTES", 5)
        _RedirectBodyHandler.final_requests = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectBodyHandler)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()
        session = librus_client_module.LibrusTimeoutSession()
        try:
            response = session.get(
                f"http://127.0.0.1:{server.server_port}/redirect", allow_redirects=False
            )
            assert response.content == b"12345"
            assert response.history == []
            assert _RedirectBodyHandler.final_requests == 0
        finally:
            session.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_session_bounds_cumulative_redirect_bodies(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_UPSTREAM_RESPONSE_BYTES", 5)
        monkeypatch.setattr(librus_client_module, "MAX_UPSTREAM_RESPONSE_CHAIN_BYTES", 7)
        _RedirectBodyHandler.final_requests = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectBodyHandler)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()
        session = librus_client_module.LibrusTimeoutSession()
        try:
            with pytest.raises(RuntimeError, match="response body is too large"):
                session.get(f"http://127.0.0.1:{server.server_port}/redirect")
            assert _RedirectBodyHandler.final_requests == 0
        finally:
            session.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    def test_session_bounds_chunked_body_by_cumulative_budget(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_UPSTREAM_RESPONSE_BYTES", 10)
        monkeypatch.setattr(librus_client_module, "MAX_UPSTREAM_RESPONSE_CHAIN_BYTES", 4)
        response = MagicMock(status_code=200, headers={})
        response.iter_content.return_value = [b"ab", b"cde"]
        session = librus_client_module.LibrusTimeoutSession()

        with (
            patch("requests.Session.send", return_value=response),
            pytest.raises(RuntimeError, match="response body is too large"),
        ):
            session.get("https://example.invalid")

        response.close.assert_called_once()

    @pytest.mark.parametrize(
        ("url", "status", "headers"),
        [
            ("https://synergia.librus.pl/ordinary", 429, {"Content-Length": "2"}),
            (
                f"https://synergia.librus.pl{librus_client_module.LOGIN_AUTHORIZATION_URL_SUFFIX}",
                200,
                {"Content-Length": "2"},
            ),
            (
                f"https://synergia.librus.pl{librus_client_module.LOGIN_AUTHORIZATION_URL_SUFFIX}",
                500,
                {"Content-Length": "2"},
            ),
        ],
    )
    def test_login_throttle_signal_is_scoped_to_login_throttle_response(self, url, status, headers):
        response = MagicMock(status_code=status, headers=headers)
        response.iter_content.return_value = [b"ok"]
        response.is_redirect = False
        request = MagicMock(url=url)
        session = librus_client_module.LibrusTimeoutSession()

        with patch("requests.Session.send", return_value=response):
            session.send(request)

        assert session._login_throttle_confirmed is False

    def test_oversized_login_throttle_response_still_records_cooldown(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_UPSTREAM_RESPONSE_BYTES", 4)
        response = MagicMock(status_code=429, headers={"Content-Length": "5"})
        request = MagicMock(
            url=f"https://synergia.librus.pl{librus_client_module.LOGIN_AUTHORIZATION_URL_SUFFIX}"
        )
        session = librus_client_module.LibrusTimeoutSession()

        with (
            patch("requests.Session.send", return_value=response),
            pytest.raises(RuntimeError, match="response body is too large"),
        ):
            session.send(request)

        assert session._login_throttle_confirmed is True

    def test_session_records_confirmed_login_throttling(self):
        response = MagicMock(status_code=429, headers={"Retry-After": "60"})
        session = librus_client_module.LibrusTimeoutSession()
        with patch("requests.Session.request", return_value=response):
            session.post("https://api.librus.pl/OAuth/Authorization?client_id=46")
        session.close()
        assert session._login_throttle_confirmed is True

    @pytest.mark.asyncio
    async def test_operation_timeout_evicts_the_client(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "UPSTREAM_OPERATION_TIMEOUT_SECONDS", 0.01)
        client = MagicMock()
        LibrusManager._instances["test_student"] = client
        release_worker = threading.Event()

        def slow_call(received_client):
            assert received_client is client
            assert release_worker.wait(timeout=5)

        with patch.object(LibrusManager, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = client
            with pytest.raises(TimeoutError, match="timed out"):
                await LibrusManager._execute("test_student", slow_call)
            with pytest.raises(RuntimeError, match="still completing"):
                await LibrusManager._execute("test_student", lambda _: "unexpected")
            client._session.close.assert_not_called()
            release_worker.set()
            for _ in range(100):
                if client._session.close.call_count == 1:
                    break
                await asyncio.sleep(0.01)
            assert await LibrusManager._execute("test_student", lambda _: "ok") == "ok"
        assert "test_student" not in LibrusManager._instances
        client._session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_timed_out_attachment_worker_cannot_publish_later(self, tmp_path, monkeypatch):
        monkeypatch.setattr(librus_client_module, "UPSTREAM_OPERATION_TIMEOUT_SECONDS", 0.01)
        client = MagicMock()
        worker_started = threading.Event()
        release_worker = threading.Event()
        late_file = tmp_path / "late.bin"

        def slow_download(received_client, message_id, file_id, download_dir, cancellation):
            assert received_client is client
            worker_started.set()
            assert release_worker.wait(timeout=5)
            cancellation.raise_if_cancelled()
            late_file.write_bytes(b"late")
            return {"path": str(late_file)}

        config = LibrusManager._get_config().model_copy(update={"download_dir": tmp_path})
        with (
            patch.object(LibrusManager, "get_client", new_callable=AsyncMock, return_value=client),
            patch.object(LibrusManager, "_get_config", return_value=config),
            patch.object(librus_client_module.scraping, "download_attachment", slow_download),
        ):
            try:
                with pytest.raises(TimeoutError, match="timed out"):
                    await LibrusManager.download_message_attachment("test_student", "1", "2")
                assert worker_started.is_set()
            finally:
                release_worker.set()
            for _ in range(100):
                if not LibrusManager._timed_out_workers:
                    break
                await asyncio.sleep(0.01)

        assert not late_file.exists()
        assert LibrusManager._timed_out_workers == {}
        client._session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancelled_attachment_worker_cannot_publish_later(self, tmp_path):
        client = MagicMock()
        worker_started = threading.Event()
        release_worker = threading.Event()
        late_file = tmp_path / "late.bin"

        def slow_download(received_client, message_id, file_id, download_dir, cancellation):
            assert received_client is client
            worker_started.set()
            assert release_worker.wait(timeout=5)
            cancellation.raise_if_cancelled()
            late_file.write_bytes(b"late")
            return {"path": str(late_file)}

        config = LibrusManager._get_config().model_copy(update={"download_dir": tmp_path})
        with (
            patch.object(LibrusManager, "get_client", new_callable=AsyncMock, return_value=client),
            patch.object(LibrusManager, "_get_config", return_value=config),
            patch.object(librus_client_module.scraping, "download_attachment", slow_download),
        ):
            task = asyncio.create_task(
                LibrusManager.download_message_attachment("test_student", "1", "2")
            )
            try:
                for _ in range(100):
                    if worker_started.is_set():
                        break
                    await asyncio.sleep(0.01)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                release_worker.set()
            for _ in range(100):
                if not LibrusManager._timed_out_workers:
                    break
                await asyncio.sleep(0.01)

        assert not late_file.exists()
        assert LibrusManager._timed_out_workers == {}
        client._session.close.assert_called_once()

    def test_evict_client_closes_its_session(self):
        client = MagicMock()
        LibrusManager._instances["test_student"] = client

        LibrusManager._evict_client("test_student")

        client._session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_timeout_does_not_start_an_auth_cooldown(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "UPSTREAM_OPERATION_TIMEOUT_SECONDS", 0.01)

        async def slow_login(*args, **kwargs):
            await asyncio.sleep(0.1)

        with (
            patch("src.librus_client.asyncio.to_thread", side_effect=slow_login),
            pytest.raises(TimeoutError, match="authentication timed out"),
        ):
            await LibrusManager.get_client("test_student")
        assert LibrusManager._auth_cooldowns == {}

    @pytest.mark.asyncio
    async def test_login_timeout_quarantines_the_alias(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "UPSTREAM_OPERATION_TIMEOUT_SECONDS", 0.01)
        release_login = threading.Event()

        class SlowClient:
            def __init__(self):
                self._session = MagicMock()
                self.cookies = None

            def get_token(self, username, password):
                assert release_login.wait(timeout=5)
                return object()

        client = SlowClient()
        with patch("src.librus_client.new_client", return_value=client):
            with pytest.raises(TimeoutError, match="authentication timed out"):
                await LibrusManager.get_client("test_student")
            with pytest.raises(RuntimeError, match="still completing"):
                await LibrusManager.get_client("test_student")
            release_login.set()
            for _ in range(100):
                if LibrusManager._timed_out_workers == {}:
                    break
                await asyncio.sleep(0.01)
        assert LibrusManager._timed_out_workers == {}

    @pytest.mark.asyncio
    async def test_password_is_unwrapped_only_for_authentication(self):
        seen = {}

        class LoginClient:
            def __init__(self):
                self._session = MagicMock()
                self.cookies = None

            def get_token(self, username, password):
                seen["username"] = username
                seen["password"] = password
                return object()

        client = LoginClient()
        with patch("src.librus_client.new_client", return_value=client):
            assert await LibrusManager.get_client("test_student") is client

        assert seen == {"username": "00000", "password": "fake"}
        assert isinstance(seen["password"], str)

    @pytest.mark.asyncio
    async def test_cancel_after_worker_completion_retires_client(self):
        client = MagicMock()
        LibrusManager._instances["test_student"] = client

        async def cancel_after_completion(workers, timeout):
            await next(iter(workers))
            raise asyncio.CancelledError

        with (
            patch("src.librus_client.asyncio.wait", side_effect=cancel_after_completion),
            pytest.raises(asyncio.CancelledError),
        ):
            await LibrusManager._run_upstream_call("test_student", client, lambda: "completed")
        assert "test_student" not in LibrusManager._instances
        client._session.close.assert_called_once()


class TestConnectionCheck:
    @pytest.mark.asyncio
    async def test_uses_one_login_and_one_profile_read_without_execute_retry(self):
        client = MagicMock()
        get_client = AsyncMock(return_value=client)
        run_call = AsyncMock(return_value=object())

        with (
            patch.object(LibrusManager, "get_client", get_client),
            patch.object(LibrusManager, "_run_upstream_call", run_call),
            patch.object(LibrusManager, "_execute") as execute,
        ):
            await LibrusManager.check_account_connection("test_student")

        get_client.assert_awaited_once_with("test_student")
        assert run_call.await_count == 1
        execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_denial_is_not_retried(self):
        from librus_apix.exceptions import AuthorizationError

        client = MagicMock()
        run_call = AsyncMock(side_effect=AuthorizationError("denied"))

        with (
            patch.object(LibrusManager, "get_client", AsyncMock(return_value=client)),
            patch.object(LibrusManager, "_run_upstream_call", run_call),
            patch.object(LibrusManager, "_evict_client") as evict,
            pytest.raises(AuthorizationError),
        ):
            await LibrusManager.check_account_connection("test_student")

        assert run_call.await_count == 1
        evict.assert_called_once_with("test_student")


class TestAuthCooldown:
    @pytest.mark.asyncio
    async def test_confirmed_throttled_login_gets_actionable_error_and_cooldown(self):
        from requests.exceptions import JSONDecodeError

        session = MagicMock(_login_throttle_confirmed=True)
        with (
            patch("src.librus_client.LibrusTimeoutSession", return_value=session),
            patch("src.librus_client.asyncio.to_thread", new_callable=AsyncMock) as to_thread,
        ):
            to_thread.side_effect = JSONDecodeError("Expecting value", "", 0)
            with pytest.raises(ValueError, match="confirmed login throttling"):
                await LibrusManager.get_client("test_student")
            with pytest.raises(ValueError, match="cooldown"):
                await LibrusManager.get_client("test_student")
            assert to_thread.await_count == 1

    @pytest.mark.asyncio
    async def test_oversized_throttled_login_starts_cooldown(self):
        session = MagicMock(_login_throttle_confirmed=True)
        with (
            patch("src.librus_client.LibrusTimeoutSession", return_value=session),
            patch("src.librus_client.asyncio.to_thread", new_callable=AsyncMock) as to_thread,
        ):
            to_thread.side_effect = librus_client_module.ResponseTooLargeError("too large")
            with pytest.raises(ValueError, match="confirmed login throttling"):
                await LibrusManager.get_client("test_student")
            with pytest.raises(ValueError, match="cooldown"):
                await LibrusManager.get_client("test_student")

        assert to_thread.await_count == 1

    @pytest.mark.asyncio
    async def test_unconfirmed_non_json_login_does_not_start_cooldown(self):
        from requests.exceptions import JSONDecodeError

        with patch("src.librus_client.asyncio.to_thread", new_callable=AsyncMock) as to_thread:
            to_thread.side_effect = [JSONDecodeError("Expecting value", "", 0), object()]
            with pytest.raises(ValueError, match="transient"):
                await LibrusManager.get_client("test_student")
            client = await LibrusManager.get_client("test_student")

        assert client is not None
        assert to_thread.await_count == 2
        assert LibrusManager._auth_cooldowns == {}

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
    async def test_transient_login_failure_does_not_start_cooldown(self):
        from requests.exceptions import ConnectionError

        with patch("src.librus_client.asyncio.to_thread", new_callable=AsyncMock) as to_thread:
            to_thread.side_effect = [ConnectionError("temporary network failure"), object()]
            with pytest.raises(ValueError, match="temporary network failure"):
                await LibrusManager.get_client("test_student")
            client = await LibrusManager.get_client("test_student")

        assert client is not None
        assert to_thread.await_count == 2
        assert LibrusManager._auth_cooldowns == {}

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
        with (
            patch.object(LibrusManager, "_execute", mock),
            pytest.raises(RuntimeError, match="get_subject_frequency"),
        ):
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

    @pytest.mark.asyncio
    @pytest.mark.parametrize("alias", [" test_student", "test_student ", "a" * 81])
    async def test_invalid_alias_shape_raises_before_creating_locks(self, alias):
        with pytest.raises(ValueError, match="student_alias"):
            await LibrusManager._execute(alias, lambda client: None)
        assert alias not in LibrusManager._client_locks


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

    @pytest.mark.asyncio
    async def test_different_alias_requests_run_concurrently(self, monkeypatch):
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
        active = {"count": 0, "max": 0}
        both_started = threading.Barrier(2, timeout=2)

        def tracked(client):
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
            both_started.wait()
            active["count"] -= 1

        with patch.object(LibrusManager, "get_client", new_callable=AsyncMock) as get_client:
            get_client.return_value = object()
            await asyncio.gather(
                LibrusManager._execute("first", tracked),
                LibrusManager._execute("second", tracked),
            )
        assert active["max"] == 2


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
    async def test_single_page_truncates_oversized_upstream_page(self):
        mock = AsyncMock(return_value=(0, _messages(0, 51)))

        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_messages("test_student")

        assert len(result["messages"]) == 50
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_received_fetches_every_page(self):
        mock = AsyncMock()
        mock.side_effect = [(1, _messages(0, 50)), _messages(1, 7)]
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
        mock.side_effect = [(5, _messages(0, 50)), _messages(1, 50)]
        result = await LibrusManager.fetch_all_messages("test_student", "received")
        assert result["pages_fetched"] == 2
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_received_exact_page_cap_is_truncated(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_ALL_MESSAGE_PAGES", 2)
        mock = AsyncMock(side_effect=[(2, _messages(0, 50)), _messages(1, 50)])

        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "received")

        assert result["pages_fetched"] == 2
        assert result["truncated"] is True
        assert mock.await_count == 2

    @pytest.mark.asyncio
    async def test_received_fetches_three_pages_below_item_cap(self):
        mock = AsyncMock(side_effect=[(2, _messages(0, 50)), _messages(1, 50), _messages(2, 7)])

        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "received")

        assert len(result["messages"]) == 107
        assert result["pages_fetched"] == 3
        assert result["truncated"] is False
        assert mock.await_count == 3

    @pytest.mark.asyncio
    async def test_received_stops_when_item_cap_is_reached(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_ALL_MESSAGE_ITEMS", 55)
        mock = AsyncMock(side_effect=[(2, _messages(0, 50)), _messages(1, 50)])

        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "received")

        assert len(result["messages"]) == 55
        assert result["pages_fetched"] == 2
        assert result["truncated"] is True
        assert mock.await_count == 2

    @pytest.mark.asyncio
    async def test_received_first_page_stops_at_item_cap(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_ALL_MESSAGE_ITEMS", 25)
        mock = AsyncMock(return_value=(2, _messages(0, 50)))

        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "received")

        assert len(result["messages"]) == 25
        assert result["pages_fetched"] == 1
        assert result["truncated"] is True
        assert mock.await_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("max_page", "truncated"), [(0, False), (1, True)])
    async def test_received_exact_first_page_cap_does_not_fetch_another_page(
        self, monkeypatch, max_page, truncated
    ):
        monkeypatch.setattr(librus_client_module, "MAX_ALL_MESSAGE_ITEMS", 50)
        mock = AsyncMock(return_value=(max_page, _messages(0, 50)))

        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "received")

        assert len(result["messages"]) == 50
        assert result["pages_fetched"] == 1
        assert result["truncated"] is truncated
        assert mock.await_count == 1

    @pytest.mark.asyncio
    async def test_received_oversized_first_page_is_truncated(self):
        mock = AsyncMock(return_value=(0, _messages(0, 51)))

        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "received")

        assert len(result["messages"]) == 50
        assert result["pages_fetched"] == 1
        assert result["truncated"] is True
        assert mock.await_count == 1

    @pytest.mark.asyncio
    async def test_received_exact_item_cap_on_last_page_is_not_truncated(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_ALL_MESSAGE_ITEMS", 57)
        mock = AsyncMock(side_effect=[(1, _messages(0, 50)), _messages(1, 7)])

        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "received")

        assert len(result["messages"]) == 57
        assert result["pages_fetched"] == 2
        assert result["truncated"] is False
        assert mock.await_count == 2

    @pytest.mark.asyncio
    async def test_received_exact_item_cap_before_last_page_is_truncated(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_ALL_MESSAGE_ITEMS", 57)
        mock = AsyncMock(side_effect=[(2, _messages(0, 50)), _messages(1, 7)])

        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "received")

        assert len(result["messages"]) == 57
        assert result["pages_fetched"] == 2
        assert result["truncated"] is True
        assert mock.await_count == 2

    @pytest.mark.asyncio
    async def test_received_oversized_later_page_stops_immediately(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_ALL_MESSAGE_ITEMS", 120)
        mock = AsyncMock(side_effect=[(2, _messages(0, 50)), _messages(1, 51)])

        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "received")

        assert len(result["messages"]) == 100
        assert result["pages_fetched"] == 2
        assert result["truncated"] is True
        assert mock.await_count == 2

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
    async def test_sent_exact_item_cap_on_short_page_is_not_truncated(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_ALL_MESSAGE_ITEMS", 55)
        mock = AsyncMock(side_effect=[_messages(0, 50), _messages(1, 5)])

        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "sent")

        assert len(result["messages"]) == 55
        assert result["pages_fetched"] == 2
        assert result["truncated"] is False
        assert mock.await_count == 2

    @pytest.mark.asyncio
    async def test_sent_overflowing_page_stops_at_item_cap(self, monkeypatch):
        monkeypatch.setattr(librus_client_module, "MAX_ALL_MESSAGE_ITEMS", 55)
        mock = AsyncMock(side_effect=[_messages(0, 50), _messages(1, 50)])

        with patch.object(LibrusManager, "_execute", mock):
            result = await LibrusManager.fetch_all_messages("test_student", "sent")

        assert len(result["messages"]) == 55
        assert result["pages_fetched"] == 2
        assert result["truncated"] is True
        assert mock.await_count == 2

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

    def test_negative_first_page_index_is_rejected(self):
        with pytest.raises(AssertionError, match="nonnegative"):
            LibrusManager._validate_first_page_result((-1, []))

    @pytest.mark.parametrize("result", [([],), (0, [], "extra")])
    def test_first_page_result_requires_exact_tuple_shape(self, result):
        with pytest.raises(AssertionError, match="max_page, items"):
            LibrusManager._validate_first_page_result(result)


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
