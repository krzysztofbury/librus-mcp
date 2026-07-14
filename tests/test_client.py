"""Tests for LibrusManager session safety: cookie isolation, per-alias
serialization, auth retry, error normalization, and bounded all-pages fetch."""

import asyncio
import dataclasses
import json
from unittest.mock import AsyncMock, patch

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
