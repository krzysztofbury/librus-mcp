"""Tests for tools added in 0.3.0: notifications, recent events, sent messages,
send_message, attachments, behaviour notes, and feature gating."""

from unittest.mock import AsyncMock, patch

import pytest
from librus_apix.notifications import NotificationData, NotificationIds

from src.notification_state import load_notification_ids
from src.scraping import Attachment, BehaviourNote
from src.server import (
    download_attachment,
    get_behaviour_notes,
    get_message_attachments,
    get_messages,
    get_new_notifications,
    get_recent_schedule_events,
    get_recipient_groups,
    get_recipients,
    mcp,
    register_optional_tools,
    send_message,
)


def _mock_execute(return_value):
    return patch(
        "src.librus_client.LibrusManager._execute",
        new_callable=AsyncMock,
        return_value=return_value,
    )


def _empty_notification_data() -> NotificationData:
    return NotificationData([], [], [], [], [], [])


def _empty_notification_ids() -> NotificationIds:
    return NotificationIds([], [], [], [], [], [])


# --- get_messages: pagination + folders ---


class TestGetMessagesPagination:
    @pytest.mark.asyncio
    async def test_received_returns_messages_and_max_page(self):
        mock = AsyncMock()
        mock.side_effect = [3, []]  # max_page, then messages
        with patch("src.librus_client.LibrusManager._execute", mock):
            result = await get_messages("test_student")
        assert result["folder"] == "received"
        assert result["page"] == 0  # 0-based: page 0 is the newest
        assert result["max_page"] == 3
        assert result["messages"] == []

    @pytest.mark.asyncio
    async def test_page_beyond_max_raises(self):
        mock = AsyncMock()
        mock.side_effect = [1]  # max_page only; messages never fetched
        with patch("src.librus_client.LibrusManager._execute", mock):
            with pytest.raises(AssertionError, match="max_page"):
                await get_messages("test_student", page=5)

    @pytest.mark.asyncio
    async def test_sent_folder_skips_max_page(self):
        mock = AsyncMock()
        mock.side_effect = [[]]  # only messages; no max_page call for sent
        with patch("src.librus_client.LibrusManager._execute", mock):
            result = await get_messages("test_student", folder="sent")
        assert result["folder"] == "sent"
        assert result["max_page"] is None
        assert mock.call_count == 1

    @pytest.mark.asyncio
    async def test_invalid_folder_raises(self):
        with pytest.raises(AssertionError, match="folder"):
            await get_messages("test_student", folder="archive")

    @pytest.mark.asyncio
    async def test_negative_page_raises(self):
        with pytest.raises(AssertionError, match="page"):
            await get_messages("test_student", page=-1)


# --- get_recent_schedule_events ---


class TestGetRecentScheduleEvents:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        with _mock_execute([]):
            result = await get_recent_schedule_events("test_student")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(AssertionError):
            await get_recent_schedule_events("")


# --- get_new_notifications: persisted state ---


class TestGetNewNotifications:
    @pytest.mark.asyncio
    async def test_first_run_passes_empty_ids_and_persists_state(self, tmp_path, monkeypatch):
        """No state file: diff against empty IDs (works for both student and
        parent accounts, unlike get_initial_notification_data which 403s on
        /uczen/index for parents)."""
        monkeypatch.setenv("LIBRUS_STATE_DIR", str(tmp_path))
        captured = {}

        async def fake_execute(alias, func, *args, **kwargs):
            captured["function"] = func.__name__
            captured["args"] = args
            return (_empty_notification_data(), _empty_notification_ids())

        with patch("src.librus_client.LibrusManager._execute", side_effect=fake_execute):
            result = await get_new_notifications("test_student")

        assert result["first_run"] is True
        assert captured["function"] == "get_new_notification_data"
        assert captured["args"][0].grades == []
        assert captured["args"][0].messages == []
        assert load_notification_ids(tmp_path, "test_student") is not None

    @pytest.mark.asyncio
    async def test_subsequent_run_passes_seen_ids(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LIBRUS_STATE_DIR", str(tmp_path))
        seen = NotificationIds(["/g/1"], [], [], [], [], [])
        from src.notification_state import save_notification_ids

        save_notification_ids(tmp_path, "test_student", seen)
        captured = {}

        async def fake_execute(alias, func, *args, **kwargs):
            captured["function"] = func.__name__
            captured["args"] = args
            updated = NotificationIds(["/g/1", "/g/2"], [], [], [], [], [])
            return (_empty_notification_data(), updated)

        with patch("src.librus_client.LibrusManager._execute", side_effect=fake_execute):
            result = await get_new_notifications("test_student")

        assert result["first_run"] is False
        assert captured["function"] == "get_new_notification_data"
        assert captured["args"][0].grades == ["/g/1"]
        # Updated ids must be persisted for the next call.
        assert load_notification_ids(tmp_path, "test_student").grades == ["/g/1", "/g/2"]

    @pytest.mark.asyncio
    async def test_result_contains_all_categories(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LIBRUS_STATE_DIR", str(tmp_path))
        with _mock_execute((_empty_notification_data(), _empty_notification_ids())):
            result = await get_new_notifications("test_student")
        for key in ("grades", "attendance", "messages", "announcements", "schedule", "homework"):
            assert key in result["new"]


# --- attachments ---


class TestGetMessageAttachments:
    @pytest.mark.asyncio
    async def test_returns_attachment_list(self):
        attachments = [Attachment("raport.pdf", "1234567", "7654321")]
        with _mock_execute(attachments):
            result = await get_message_attachments("test_student", "1234567")
        assert result[0]["filename"] == "raport.pdf"
        assert result[0]["file_id"] == "7654321"

    @pytest.mark.asyncio
    async def test_empty_message_id_raises(self):
        with pytest.raises(AssertionError, match="message_id"):
            await get_message_attachments("test_student", "")


class TestDownloadAttachmentTool:
    @pytest.mark.asyncio
    async def test_returns_download_info(self):
        info = {
            "path": "/tmp/raport.pdf",
            "filename": "raport.pdf",
            "size": 22337,
            "content_type": "application/pdf",
        }
        with _mock_execute(info):
            result = await download_attachment("test_student", "1234567", "7654321")
        assert result["path"] == "/tmp/raport.pdf"
        assert result["size"] == 22337

    @pytest.mark.asyncio
    async def test_empty_file_id_raises(self):
        with pytest.raises(AssertionError, match="file_id"):
            await download_attachment("test_student", "1234567", "")


# --- behaviour notes ---


class TestGetBehaviourNotes:
    @pytest.mark.asyncio
    async def test_returns_notes(self):
        notes = [BehaviourNote("2026-05-10", "Kowalski Jan", "negatywna", "Treść uwagi")]
        with _mock_execute(notes):
            result = await get_behaviour_notes("test_student")
        assert result[0]["teacher"] == "Kowalski Jan"

    @pytest.mark.asyncio
    async def test_empty_alias_raises(self):
        with pytest.raises(AssertionError):
            await get_behaviour_notes("")


# --- send_message ---


class TestSendMessageTools:
    @pytest.mark.asyncio
    async def test_recipient_groups(self):
        with _mock_execute(["nauczyciel", "wychowawca"]):
            result = await get_recipient_groups("test_student")
        assert result == ["nauczyciel", "wychowawca"]

    @pytest.mark.asyncio
    async def test_recipients(self):
        with _mock_execute({"Kowalski Jan": "12345"}):
            result = await get_recipients("test_student", "nauczyciel")
        assert result == {"Kowalski Jan": "12345"}

    @pytest.mark.asyncio
    async def test_recipients_empty_group_raises(self):
        with pytest.raises(AssertionError, match="group"):
            await get_recipients("test_student", "")

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        with _mock_execute((True, "Wiadomość została wysłana")):
            result = await send_message("test_student", "Temat", "Treść", ["12345"])
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_send_message_empty_title_raises(self):
        with pytest.raises(AssertionError, match="title"):
            await send_message("test_student", "", "Treść", ["12345"])

    @pytest.mark.asyncio
    async def test_send_message_empty_recipients_raises(self):
        with pytest.raises(AssertionError, match="recipient"):
            await send_message("test_student", "Temat", "Treść", [])


# --- feature gating ---


class TestRegisterOptionalTools:
    def test_all_disabled_registers_nothing(self, monkeypatch):
        monkeypatch.setenv(
            "LIBRUS_FEATURES",
            '{"notifications": false, "attachments": false,'
            ' "behaviour_notes": false, "send_message": false}',
        )
        registered = register_optional_tools()
        assert registered == []

    @pytest.mark.asyncio
    async def test_defaults_register_read_tools_but_not_send(self, monkeypatch):
        monkeypatch.delenv("LIBRUS_FEATURES", raising=False)
        registered = register_optional_tools()
        tool_names = {tool.name for tool in await mcp.list_tools()}
        assert "get_new_notifications" in tool_names
        assert "get_message_attachments" in tool_names
        assert "download_attachment" in tool_names
        assert "get_behaviour_notes" in tool_names
        assert "send_message" not in tool_names
        assert "send_message" not in registered

    def test_second_call_is_idempotent(self, monkeypatch):
        monkeypatch.delenv("LIBRUS_FEATURES", raising=False)
        register_optional_tools()
        assert register_optional_tools() == []
