"""Tests for own-scraping additions: message attachments and behaviour notes (uwagi).

Attachment, empty-note, and final-grade HTML mirror Synergia markup captured on
2026-06-11. Populated behaviour-note examples remain synthetic parser contracts.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import pytest
from librus_apix.exceptions import ParseError

from src.scraping import (
    Attachment,
    AttachmentDownloadCancelled,
    BehaviourNote,
    DownloadCancellation,
    download_attachment,
    parse_attachments,
    parse_behaviour_notes,
    parse_final_grades,
)

# Mirrors the real message detail page: "Pliki:" table after message content.
ATTACHMENT_HTML = """
<html><body>
<table class="stretch">
  <tr><td class="medium left"><b>Nadawca</b></td><td class="left">Nowak Anna [Nauczyciel]</td></tr>
  <tr><td class="medium left"><b>Temat</b></td><td class="left">Diagnoza</td></tr>
</table>
<div class="container-message-content">W zalaczniku raport.</div>
<table>
  <tr><td colspan="2" class="left"><b>Pliki:</b></td></tr>
  <tr>
    <td>
      <!-- icon -->
      <img src="/assets/img/filetype_icons/pdf.png"/>
      <!-- name -->
      raport_klasowy.pdf
    </td>
    <td>
      &nbsp;
      <a href="javascript:void(0);">
        <img src="/assets/img/homework_files_icons/download.png"
             onClick="
                 otworz_w_nowym_oknie(
                     &quot;\\/wiadomosci\\/pobierz_zalacznik\\/1234567\\/7654321&quot;,
                     &quot;o2&quot;,
                     420,
                     250)
             "/>
      </a>
    </td>
  </tr>
  <tr>
    <td>
      <img src="/assets/img/filetype_icons/jpg.png"/>
      zdjecie klasowe.jpg
    </td>
    <td>
      <a href="javascript:void(0);">
        <img src="/assets/img/homework_files_icons/download.png"
             onClick="otworz_w_nowym_oknie(&quot;\\/wiadomosci\\/pobierz_zalacznik\\/1234567\\/99887766&quot;,&quot;o2&quot;,420,250)"/>
      </a>
    </td>
  </tr>
</table>
</body></html>
"""

NO_ATTACHMENT_HTML = """
<html><body>
<table class="stretch">
  <tr><td class="medium left"><b>Nadawca</b></td><td class="left">Nowak Anna</td></tr>
</table>
<div class="container-message-content">Bez zalacznikow.</div>
</body></html>
"""

# Real empty-state structure captured live.
UWAGI_EMPTY_HTML = """
<html><body>
<div class="container-background">
  <br/>
  <div class="container border-red resizeable center">
    <div class="container-background">
      <p class="msgEmptyTable">Brak uwag</p>
    </div>
  </div>
</div>
</body></html>
"""

# Label-pair detail-table shape used across Synergia pages.
UWAGI_LABEL_PAIRS_HTML = """
<html><body>
<div class="container-background">
<table class="decorated">
  <tr><td class="medium left">Data dodania</td><td class="left">2026-05-10 12:00:00</td></tr>
  <tr><td class="medium left">Nauczyciel</td><td class="left">Kowalski Jan</td></tr>
  <tr><td class="medium left">Rodzaj</td><td class="left">uwaga negatywna</td></tr>
  <tr><td class="medium left">Treść</td><td class="left">Przeszkadza na lekcji.</td></tr>
</table>
<table class="decorated">
  <tr><td class="medium left">Data dodania</td><td class="left">2026-05-12 09:30:00</td></tr>
  <tr><td class="medium left">Nauczyciel</td><td class="left">Nowak Anna</td></tr>
  <tr><td class="medium left">Rodzaj</td><td class="left">pochwała</td></tr>
  <tr><td class="medium left">Uwaga</td><td class="left">Pomoc koleżance.</td></tr>
</table>
</div>
</body></html>
"""

# Column-table shape (header row + line0/line1 rows) used by Synergia lists.
UWAGI_COLUMNS_HTML = """
<html><body>
<div class="container-background">
<table class="decorated">
  <thead>
    <tr><td>Data</td><td>Nauczyciel</td><td>Rodzaj</td><td>Treść</td></tr>
  </thead>
  <tbody>
    <tr class="line0"><td>2026-05-10</td><td>Kowalski Jan</td><td>negatywna</td><td>Bieganie po korytarzu.</td></tr>
    <tr class="line1"><td>2026-05-12</td><td>Nowak Anna</td><td>pozytywna</td><td>Reprezentowanie szkoły.</td></tr>
  </tbody>
</table>
</div>
</body></html>
"""


class TestParseAttachments:
    def test_finds_all_attachments(self):
        attachments = parse_attachments(ATTACHMENT_HTML)
        assert len(attachments) == 2
        assert attachments[0] == Attachment(
            filename="raport_klasowy.pdf", message_id="1234567", file_id="7654321"
        )
        assert attachments[1].filename == "zdjecie klasowe.jpg"
        assert attachments[1].file_id == "99887766"

    def test_no_attachments_returns_empty(self):
        assert parse_attachments(NO_ATTACHMENT_HTML) == []

    def test_empty_html_raises(self):
        with pytest.raises(ParseError, match="empty"):
            parse_attachments("")

    def test_whitespace_only_html_raises(self):
        with pytest.raises(ParseError, match="empty"):
            parse_attachments(" \n\t")


class TestParseBehaviourNotes:
    def test_empty_state_returns_empty_list(self):
        assert parse_behaviour_notes(UWAGI_EMPTY_HTML) == []

    def test_label_pair_tables(self):
        notes = parse_behaviour_notes(UWAGI_LABEL_PAIRS_HTML)
        assert len(notes) == 2
        assert notes[0] == BehaviourNote(
            date="2026-05-10 12:00:00",
            teacher="Kowalski Jan",
            category="uwaga negatywna",
            content="Przeszkadza na lekcji.",
        )
        # "Uwaga" label is accepted as content too.
        assert notes[1].content == "Pomoc koleżance."
        assert notes[1].category == "pochwała"

    def test_column_tables(self):
        notes = parse_behaviour_notes(UWAGI_COLUMNS_HTML)
        assert len(notes) == 2
        assert notes[0].date == "2026-05-10"
        assert notes[0].teacher == "Kowalski Jan"
        assert notes[1].content == "Reprezentowanie szkoły."

    def test_empty_html_raises(self):
        with pytest.raises(ParseError, match="empty"):
            parse_behaviour_notes("")

    @pytest.mark.parametrize(
        "html",
        [
            UWAGI_LABEL_PAIRS_HTML.replace("Data dodania", "Kiedy", 1),
            UWAGI_LABEL_PAIRS_HTML.replace("Treść", "Opis", 1),
            UWAGI_COLUMNS_HTML.replace("<td>Data</td>", "<td>Kiedy</td>", 1),
            UWAGI_COLUMNS_HTML.replace("<td>Treść</td>", "<td>Opis</td>", 1),
        ],
    )
    def test_note_missing_required_date_or_content_raises(self, html):
        with pytest.raises(ParseError, match="missing required fields"):
            parse_behaviour_notes(html)

    def test_teacher_and_category_are_optional(self):
        html = """
        <table class="decorated">
          <tr><td>Data</td><td>2026-05-10</td></tr>
          <tr><td>Treść</td><td>Pomoc podczas lekcji.</td></tr>
        </table>
        """

        assert parse_behaviour_notes(html) == [
            BehaviourNote("2026-05-10", "", "", "Pomoc podczas lekcji.")
        ]

    @pytest.mark.parametrize(
        "html",
        [
            UWAGI_COLUMNS_HTML.replace(
                "<td>Bieganie po korytarzu.</td>",
                "<td>Bieganie po korytarzu.</td><td>unexpected</td>",
                1,
            ),
            UWAGI_COLUMNS_HTML.replace("<td>Kowalski Jan</td>", "", 1),
        ],
    )
    def test_malformed_column_row_does_not_return_partial_notes(self, html):
        with pytest.raises(ParseError, match="does not match"):
            parse_behaviour_notes(html)

    def test_column_values_are_trimmed(self):
        html = UWAGI_COLUMNS_HTML.replace(
            "<td>Bieganie po korytarzu.</td>",
            "<td>  Bieganie po korytarzu.  </td>",
            1,
        )

        assert parse_behaviour_notes(html)[0].content == "Bieganie po korytarzu."

    def test_nested_rows_do_not_become_notes(self):
        html = UWAGI_COLUMNS_HTML.replace(
            "Bieganie po korytarzu.",
            "Bieganie po korytarzu.<table><tr><td>nested</td></tr></table>",
            1,
        )

        notes = parse_behaviour_notes(html)
        assert len(notes) == 2
        assert notes[0].date == "2026-05-10"

    def test_nested_markup_in_label_pair_value_is_not_an_extra_cell(self):
        html = """
        <table class="decorated">
          <tr><td>Data</td><td>2026-05-10</td></tr>
          <tr><td>Treść</td><td>Pomoc<table><tr><td>detail</td></tr></table></td></tr>
        </table>
        """

        notes = parse_behaviour_notes(html)
        assert len(notes) == 1
        assert notes[0].date == "2026-05-10"


# --- download_attachment with mocked HTTP ---


class FakeRedirectResponse:
    def __init__(self, status_code=302, location="https://sandbox.librus.pl/GetFile/abc123"):
        self.status_code = status_code
        self.headers = {"Location": location} if location else {}


class FakeStreamResponse:
    """Mimics a streaming requests.Response used as a context manager."""

    def __init__(self, status_code=200, content=b"%PDF-1.4 data", headers=None):
        self.status_code = status_code
        self._content = content
        self.headers = headers if headers is not None else {}
        self.iterated = False
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def close(self):
        self.closed = True

    def iter_content(self, chunk_size):
        self.iterated = True
        for offset in range(0, len(self._content), chunk_size):
            yield self._content[offset : offset + chunk_size]


class FakeClient:
    BASE_URL = "https://synergia.librus.pl"

    def __init__(self):
        self.cookies = {"synergia_session": "secret-cookie"}
        self.proxy = {}
        self.token = type(
            "FakeToken", (), {"access_cookies": staticmethod(lambda: {"DZIENNIKSID": "sid"})}
        )()


def _patch_http(responses):
    from unittest.mock import MagicMock

    mock = MagicMock(side_effect=list(responses))
    return patch("src.scraping.requests.get", mock), mock


class TestDownloadAttachment:
    def _responses(self, filename='attachment; filename="raport.pdf"', content=b"%PDF-1.4 data"):
        headers = {"Content-Disposition": filename, "Content-Type": "application/pdf"}
        return [FakeRedirectResponse(), FakeStreamResponse(content=content, headers=headers)]

    def test_writes_file_and_returns_info(self, tmp_path):
        from src.scraping import download_attachment

        patcher, mock = _patch_http(self._responses())
        with patcher:
            info = download_attachment(FakeClient(), "1234567", "7654321", tmp_path)
        assert (tmp_path / "raport.pdf").read_bytes() == b"%PDF-1.4 data"
        assert info["filename"] == "raport.pdf"
        assert info["size"] == 13
        assert info["content_type"] == "application/pdf"
        # First request: authenticated, redirects disabled.
        first_call = mock.call_args_list[0]
        assert first_call.kwargs["allow_redirects"] is False
        assert "synergia_session" in first_call.kwargs["cookies"]
        # Second request: signed sandbox URL with /get appended and NO cookies.
        second_call = mock.call_args_list[1]
        assert second_call.args[0] == "https://sandbox.librus.pl/GetFile/abc123/get"
        assert "cookies" not in second_call.kwargs
        assert second_call.kwargs["headers"]["Accept-Encoding"] == "identity"

    def test_final_name_appears_only_after_complete_download(self, tmp_path):
        from src.scraping import download_attachment

        class InspectingResponse(FakeStreamResponse):
            def iter_content(self, chunk_size):
                yield b"first"
                assert not (tmp_path / "atomic.bin").exists()
                yield b"second"

        response = InspectingResponse(headers={"Content-Disposition": 'filename="atomic.bin"'})
        patcher, _ = _patch_http([FakeRedirectResponse(), response])
        with patcher:
            info = download_attachment(FakeClient(), "1", "2", tmp_path)
        assert info["size"] == 11
        assert (tmp_path / "atomic.bin").read_bytes() == b"firstsecond"
        assert list(tmp_path.glob("*.tmp")) == []

    def test_response_close_failure_does_not_publish_file(self, tmp_path):
        from src.scraping import download_attachment

        class FailingCloseResponse(FakeStreamResponse):
            def __exit__(self, *args):
                raise OSError("response close failed")

        response = FailingCloseResponse(
            headers={"Content-Disposition": 'filename="not-published.bin"'}
        )
        patcher, _ = _patch_http([FakeRedirectResponse(), response])
        with patcher, pytest.raises(OSError, match="response close failed"):
            download_attachment(FakeClient(), "1", "2", tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_unsupported_hard_links_raise_actionable_error(self, tmp_path):
        from src.scraping import download_attachment

        patcher, _ = _patch_http(self._responses())
        with (
            patcher,
            patch("src.scraping.os.link", side_effect=OSError("not supported")),
            pytest.raises(ValueError, match="filesystem must support hard links"),
        ):
            download_attachment(FakeClient(), "1", "2", tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_path_traversal_in_filename_is_stripped(self, tmp_path):
        from src.scraping import download_attachment

        patcher, _ = _patch_http(self._responses(filename='attachment; filename="../../evil.sh"'))
        with patcher:
            info = download_attachment(FakeClient(), "1", "2", tmp_path)
        assert info["filename"] == "evil.sh"
        assert (tmp_path / "evil.sh").exists()
        assert not (tmp_path.parent / "evil.sh").exists()

    def test_missing_disposition_falls_back_to_ids(self, tmp_path):
        from src.scraping import download_attachment

        patcher, _ = _patch_http([FakeRedirectResponse(), FakeStreamResponse(content=b"data")])
        with patcher:
            info = download_attachment(FakeClient(), "11", "22", tmp_path)
        assert info["filename"] == "attachment_11_22"

    def test_no_redirect_raises_token_error(self, tmp_path):
        from librus_apix.exceptions import TokenError

        from src.scraping import download_attachment

        patcher, _ = _patch_http([FakeRedirectResponse(status_code=200, location=None)])
        with patcher, pytest.raises(TokenError, match="did not redirect"):
            download_attachment(FakeClient(), "1", "2", tmp_path)

    def test_redirect_to_foreign_host_raises(self, tmp_path):
        from librus_apix.exceptions import TokenError

        from src.scraping import download_attachment

        patcher, mock = _patch_http(
            [FakeRedirectResponse(location="https://evil.example/GetFile/abc123")]
        )
        with patcher, pytest.raises(TokenError, match="unexpected attachment redirect"):
            download_attachment(FakeClient(), "1", "2", tmp_path)
        # The forged Location must never be requested.
        assert mock.call_count == 1

    def test_redirect_to_plain_http_raises(self, tmp_path):
        from librus_apix.exceptions import TokenError

        from src.scraping import download_attachment

        patcher, _ = _patch_http(
            [FakeRedirectResponse(location="http://sandbox.librus.pl/GetFile/abc123")]
        )
        with patcher, pytest.raises(TokenError, match="unexpected attachment redirect"):
            download_attachment(FakeClient(), "1", "2", tmp_path)

    def test_redirect_with_odd_port_raises(self, tmp_path):
        from librus_apix.exceptions import TokenError

        from src.scraping import download_attachment

        patcher, _ = _patch_http(
            [FakeRedirectResponse(location="https://sandbox.librus.pl:8080/GetFile/abc123")]
        )
        with patcher, pytest.raises(TokenError, match="unexpected attachment redirect"):
            download_attachment(FakeClient(), "1", "2", tmp_path)

    def test_redirect_with_query_raises(self, tmp_path):
        from librus_apix.exceptions import TokenError

        from src.scraping import download_attachment

        patcher, _ = _patch_http(
            [FakeRedirectResponse(location="https://sandbox.librus.pl/GetFile/abc?key=1")]
        )
        with patcher, pytest.raises(TokenError, match="unexpected attachment redirect"):
            download_attachment(FakeClient(), "1", "2", tmp_path)

    def test_dot_dot_filename_falls_back_to_ids(self, tmp_path):
        """A disposition of '..' survives an emptiness check but sanitizes to
        ''; it must fall back to the ID-based name, not create ' (1)' files."""
        from src.scraping import download_attachment

        patcher, _ = _patch_http(self._responses(filename='attachment; filename=".."'))
        with patcher:
            info = download_attachment(FakeClient(), "11", "22", tmp_path)
        assert info["filename"] == "attachment_11_22"

    def test_download_uses_client_proxy(self, tmp_path):
        from src.scraping import download_attachment

        client = FakeClient()
        client.proxy = {"https": "http://proxy.local:3128"}
        patcher, mock = _patch_http(self._responses())
        with patcher:
            download_attachment(client, "1", "2", tmp_path)
        for call in mock.call_args_list:
            assert call.kwargs["proxies"] == client.proxy

    def test_empty_body_raises(self, tmp_path):
        from src.scraping import download_attachment

        patcher, _ = _patch_http(self._responses(content=b""))
        with patcher, pytest.raises(ValueError, match="empty"):
            download_attachment(FakeClient(), "1", "2", tmp_path)

    def test_oversized_body_raises(self, tmp_path, monkeypatch):
        from src import scraping

        monkeypatch.setattr(scraping, "MAX_ATTACHMENT_BYTES", 8)
        patcher, _ = _patch_http(self._responses(content=b"0123456789"))
        with patcher, pytest.raises(ValueError, match="byte limit"):
            scraping.download_attachment(FakeClient(), "1", "2", tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_body_at_exact_size_limit_is_allowed(self, tmp_path, monkeypatch):
        from src import scraping

        content = b"exact"
        monkeypatch.setattr(scraping, "MAX_ATTACHMENT_BYTES", len(content))
        responses = self._responses(content=content)
        responses[1].headers["Content-Length"] = str(len(content))
        patcher, _ = _patch_http(responses)

        with patcher:
            info = scraping.download_attachment(FakeClient(), "1", "2", tmp_path)

        assert info["size"] == len(content)

    def test_oversized_content_length_fails_before_streaming(self, tmp_path, monkeypatch):
        from src import scraping

        monkeypatch.setattr(scraping, "MAX_ATTACHMENT_BYTES", 8)
        response = FakeStreamResponse(
            content=b"0123456789",
            headers={"Content-Length": "10", "Content-Disposition": 'filename="large.bin"'},
        )
        patcher, _ = _patch_http([FakeRedirectResponse(), response])
        with patcher, pytest.raises(ValueError, match="byte limit"):
            scraping.download_attachment(FakeClient(), "1", "2", tmp_path)
        assert response.iterated is False
        assert list(tmp_path.iterdir()) == []

    def test_encoded_response_is_rejected_before_streaming(self, tmp_path):
        response = FakeStreamResponse(
            headers={
                "Content-Encoding": "gzip",
                "Content-Disposition": 'filename="encoded.bin"',
            }
        )
        patcher, _ = _patch_http([FakeRedirectResponse(), response])

        with patcher, pytest.raises(ValueError, match="content encoding"):
            download_attachment(FakeClient(), "1", "2", tmp_path)

        assert response.iterated is False
        assert list(tmp_path.iterdir()) == []

    def test_slash_in_file_id_raises(self, tmp_path):
        from src.scraping import download_attachment

        with pytest.raises(ValueError, match="numeric ID"):
            download_attachment(FakeClient(), "1", "2/3", tmp_path)

    def test_existing_file_is_not_overwritten(self, tmp_path):
        from src.scraping import download_attachment

        (tmp_path / "raport.pdf").write_bytes(b"original")
        patcher, _ = _patch_http(self._responses())
        with patcher:
            info = download_attachment(FakeClient(), "1", "2", tmp_path)
        assert (tmp_path / "raport.pdf").read_bytes() == b"original"
        assert info["filename"] == "raport (1).pdf"
        assert (tmp_path / "raport (1).pdf").read_bytes() == b"%PDF-1.4 data"

    def test_symlink_is_not_followed(self, tmp_path):
        from src.scraping import download_attachment

        outside_target = tmp_path.parent / "outside.pdf"
        outside_target.write_bytes(b"outside")
        (tmp_path / "downloads").mkdir()
        (tmp_path / "downloads" / "raport.pdf").symlink_to(outside_target)
        patcher, _ = _patch_http(self._responses())
        with patcher:
            info = download_attachment(FakeClient(), "1", "2", tmp_path / "downloads")
        # The symlink target must stay untouched; content lands in a new file.
        assert outside_target.read_bytes() == b"outside"
        assert info["filename"] == "raport (1).pdf"

    def test_pre_cancelled_download_makes_no_request(self, tmp_path):
        cancellation = DownloadCancellation()
        cancellation.cancel()

        with (
            patch("src.scraping.requests.get") as get,
            pytest.raises(AttachmentDownloadCancelled),
        ):
            download_attachment(FakeClient(), "1", "2", tmp_path, cancellation)

        get.assert_not_called()
        assert list(tmp_path.iterdir()) == []

    def test_pre_cancelled_token_immediately_aborts_registered_response(self):
        cancellation = DownloadCancellation()
        cancellation.cancel()
        abort = MagicMock()

        cancellation.set_abort(abort)

        abort.assert_called_once_with()

    def test_live_response_abort_uses_daemon_thread(self):
        cancellation = DownloadCancellation()
        cancellation.set_abort(MagicMock())

        with patch("src.scraping.Thread") as thread:
            cancellation.cancel()

        assert thread.call_args.kwargs["daemon"] is True
        assert thread.call_args.kwargs["name"] == "librus-attachment-abort"
        thread.return_value.start.assert_called_once_with()

    def test_abort_failure_does_not_mask_cancellation(self, capsys):
        cancellation = DownloadCancellation()
        cancellation.cancel()
        cancellation._abort_safely(MagicMock(side_effect=OSError("abort failed")))

        with pytest.raises(AttachmentDownloadCancelled):
            cancellation.raise_if_cancelled()
        assert "response abort failed" in capsys.readouterr().err

    def test_cancellation_during_stream_removes_temporary_file(self, tmp_path):
        cancellation = DownloadCancellation()

        class CancellingResponse(FakeStreamResponse):
            def iter_content(self, chunk_size):
                yield b"first"
                cancellation.cancel()
                yield b"second"

        response = CancellingResponse(headers={"Content-Disposition": 'filename="late.bin"'})
        patcher, _ = _patch_http([FakeRedirectResponse(), response])

        with patcher, pytest.raises(AttachmentDownloadCancelled):
            download_attachment(FakeClient(), "1", "2", tmp_path, cancellation)

        assert list(tmp_path.iterdir()) == []

    def test_cleanup_failure_does_not_mask_cancellation(self, tmp_path, capsys):
        cancellation = DownloadCancellation()

        class CancellingResponse(FakeStreamResponse):
            def iter_content(self, chunk_size):
                yield b"first"
                cancellation.cancel()
                yield b"second"

        response = CancellingResponse(headers={"Content-Disposition": 'filename="late.bin"'})
        patcher, _ = _patch_http([FakeRedirectResponse(), response])

        with (
            patcher,
            patch("src.scraping.Path.unlink", side_effect=OSError("cleanup failed")),
            pytest.raises(AttachmentDownloadCancelled),
        ):
            download_attachment(FakeClient(), "1", "2", tmp_path, cancellation)

        assert "temporary file cleanup failed" in capsys.readouterr().err
        [temporary_path] = list(tmp_path.iterdir())
        temporary_path.unlink()

    def test_concurrent_temporary_file_removal_is_silent(self, tmp_path, capsys):
        class RemovingResponse(FakeStreamResponse):
            def iter_content(self, chunk_size):
                [temporary_path] = list(tmp_path.iterdir())
                temporary_path.unlink()
                raise OSError("download failed")

        response = RemovingResponse(headers={"Content-Disposition": 'filename="late.bin"'})
        patcher, _ = _patch_http([FakeRedirectResponse(), response])

        with patcher, pytest.raises(OSError, match="download failed"):
            download_attachment(FakeClient(), "1", "2", tmp_path)

        assert capsys.readouterr().err == ""

    def test_cancellation_after_response_close_prevents_publication(self, tmp_path):
        cancellation = DownloadCancellation()

        class CancelOnCloseResponse(FakeStreamResponse):
            def __exit__(self, *exc_info):
                cancellation.cancel()
                return False

        response = CancelOnCloseResponse(headers={"Content-Disposition": 'filename="late.bin"'})
        patcher, _ = _patch_http([FakeRedirectResponse(), response])

        with patcher, pytest.raises(AttachmentDownloadCancelled):
            download_attachment(FakeClient(), "1", "2", tmp_path, cancellation)

        assert list(tmp_path.iterdir()) == []

    def test_cancellation_aborts_blocked_response(self, tmp_path):
        cancellation = DownloadCancellation()
        stream_started = threading.Event()
        response_closed = threading.Event()
        errors = []

        class BlockingResponse(FakeStreamResponse):
            def iter_content(self, chunk_size):
                stream_started.set()
                assert response_closed.wait(timeout=5)
                raise OSError("response aborted")

            def close(self):
                super().close()
                response_closed.set()

        response = BlockingResponse(headers={"Content-Disposition": 'filename="late.bin"'})
        patcher, _ = _patch_http([FakeRedirectResponse(), response])

        def run_download():
            try:
                download_attachment(FakeClient(), "1", "2", tmp_path, cancellation)
            except OSError as error:
                errors.append(error)

        with patcher:
            worker = threading.Thread(target=run_download)
            worker.start()
            assert stream_started.wait(timeout=5)
            cancellation.cancel()
            worker.join(timeout=5)

        assert not worker.is_alive()
        assert response.closed is True
        assert len(errors) == 1
        assert isinstance(errors[0], OSError)
        assert list(tmp_path.iterdir()) == []

    def test_slow_drip_body_obeys_absolute_deadline(self, tmp_path, monkeypatch):
        from src import scraping

        class SlowDripHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                for _ in range(100):
                    try:
                        self.wfile.write(b"x")
                        self.wfile.flush()
                    except BrokenPipeError, ConnectionResetError:
                        return
                    time.sleep(0.02)

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowDripHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        monkeypatch.setattr(scraping, "DOWNLOAD_DEADLINE_SECONDS", 0.05)
        started = time.monotonic()
        try:
            with pytest.raises(ValueError, match="deadline"):
                scraping._stream_attachment(
                    f"http://127.0.0.1:{server.server_port}/slow",
                    {},
                    tmp_path,
                    "slow.bin",
                    DownloadCancellation(),
                )
            elapsed = time.monotonic() - started
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

        assert elapsed < 0.5
        assert list(tmp_path.iterdir()) == []

    def test_deadline_is_checked_before_and_after_each_raw_read(self):
        from src import scraping

        raw = MagicMock()
        raw.read1.return_value = b"x"
        response = type("Response", (), {"raw": raw})()

        for expired_at in (10.0, 11.0):
            raw.reset_mock()
            with (
                patch.object(scraping.time, "monotonic", return_value=expired_at),
                pytest.raises(ValueError, match="deadline"),
            ):
                list(scraping._iter_attachment_chunks(response, 10.0, DownloadCancellation()))
            raw.read1.assert_not_called()

            with (
                patch.object(scraping.time, "monotonic", side_effect=[9.0, expired_at]),
                pytest.raises(ValueError, match="deadline"),
            ):
                list(scraping._iter_attachment_chunks(response, 10.0, DownloadCancellation()))
        raw.read1.assert_called_once_with(scraping.DOWNLOAD_CHUNK_BYTES, decode_content=False)

    def test_raw_read_disables_content_decoding(self):
        from src import scraping

        class Raw:
            def __init__(self):
                self.chunks = iter([b"decoded", b""])

            def read1(self, chunk_size, *, decode_content):
                assert chunk_size == scraping.DOWNLOAD_CHUNK_BYTES
                assert decode_content is False
                return next(self.chunks)

        response = type("Response", (), {"raw": Raw()})()

        assert list(
            scraping._iter_attachment_chunks(response, float("inf"), DownloadCancellation())
        ) == [b"decoded"]

    def test_response_without_raw_read1_uses_iter_content(self):
        from src import scraping

        class Response:
            raw = object()

            @staticmethod
            def iter_content(chunk_size):
                assert chunk_size == scraping.DOWNLOAD_CHUNK_BYTES
                yield b"fallback"

        assert list(
            scraping._iter_attachment_chunks(Response(), float("inf"), DownloadCancellation())
        ) == [b"fallback"]

    def test_publication_and_cancellation_are_ordered(self, tmp_path):
        from src import scraping

        temporary_path = tmp_path / ".download.tmp"
        temporary_path.write_bytes(b"complete")
        cancellation = DownloadCancellation()
        publication_started = threading.Event()
        release_publication = threading.Event()
        real_link = scraping.os.link

        def blocking_link(*args, **kwargs):
            publication_started.set()
            assert release_publication.wait(timeout=5)
            return real_link(*args, **kwargs)

        with patch.object(scraping.os, "link", side_effect=blocking_link):
            publisher = threading.Thread(
                target=scraping._publish_unique_file,
                args=(temporary_path, "complete.bin", cancellation),
            )
            publisher.start()
            assert publication_started.wait(timeout=5)
            cancellation.cancel()
            assert cancellation.publication_is_idle() is False
            assert cancellation._publication_lock.locked()
            release_publication.set()
            publisher.join(timeout=5)

        assert not publisher.is_alive()
        assert cancellation.publication_is_idle() is True
        assert (tmp_path / "complete.bin").read_bytes() == b"complete"


class TestSingleHtmlParse:
    def test_attachment_page_is_parsed_once(self, monkeypatch):
        from src import scraping

        class PageClient:
            MESSAGE_URL = "https://synergia.librus.pl/wiadomosci"

            @staticmethod
            def get(url):
                return type("Response", (), {"text": NO_ATTACHMENT_HTML})()

        original = scraping.BeautifulSoup
        calls = {"count": 0}

        def counting_soup(*args, **kwargs):
            calls["count"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(scraping, "BeautifulSoup", counting_soup)
        assert scraping.get_attachments(PageClient(), "1") == []
        assert calls["count"] == 1

    def test_empty_attachment_response_raises(self):
        from src import scraping

        class PageClient:
            MESSAGE_URL = "https://synergia.librus.pl/wiadomosci"

            @staticmethod
            def get(url):
                return type("Response", (), {"text": ""})()

        with pytest.raises(ParseError, match="empty"):
            scraping.get_attachments(PageClient(), "1")

    def test_whitespace_only_attachment_response_raises(self):
        from src import scraping

        class PageClient:
            MESSAGE_URL = "https://synergia.librus.pl/wiadomosci"

            @staticmethod
            def get(url):
                return type("Response", (), {"text": " \n\t"})()

        with pytest.raises(ParseError, match="empty"):
            scraping.get_attachments(PageClient(), "1")


UWAGI_UNRECOGNIZED_HTML = """
<html><body>
<div class="container-background">
<table class="decorated">
  <tr><td>Filtruj</td><td><select><option>2026</option></select></td></tr>
</table>
</div>
</body></html>
"""


class TestUnrecognizedUwagiLayout:
    def test_tables_without_parseable_notes_raise(self):
        """A page with neither the empty marker nor parseable notes must fail
        loudly — a silent [] here would read as 'no behaviour notes'."""
        with pytest.raises(ParseError, match="unrecognized"):
            parse_behaviour_notes(UWAGI_UNRECOGNIZED_HTML)

    def test_nested_label_pair_rows_do_not_fabricate_a_note(self):
        html = """
        <table class="decorated">
          <tr><td>Wrapper<table><tr><td>Data</td><td>2026-01-01</td></tr></table></td></tr>
        </table>
        """

        with pytest.raises(ParseError, match="unrecognized"):
            parse_behaviour_notes(html)


# --- final grades (przewidywane roczne / roczne) ---

# Mirrors the real przegladaj_oceny table captured live 2026-06-11:
# thead with title attributes, 12-cell line0/line1 rows, nested noise rows.
FINAL_GRADES_HTML = """
<html><body>
<table class="decorated stretch">
<thead>
  <tr><td colspan="2"></td><td colspan="4" class="colspan center"><span>Okres 1</span></td>
      <td colspan="3" class="colspan center"><span>Okres 2</span></td>
      <td colspan="3" class="colspan center"><span>Koniec roku</span></td></tr>
  <tr>
    <td class="no-border-top spacing">Oceny bieżące</td>
    <td title="Średnia ocen<br> z pierwszego okresu">Śr.I</td>
    <td title="Przewidywana ocena śródroczna<br> z pierwszego okresu">(I)</td>
    <td title="Ocena śródroczna z pierwszego okresu">I</td>
    <td>Oceny bieżące</td>
    <td title="Średnia ocen z drugiego okresu">Śr.II</td>
    <td title="Ocena śródroczna z drugiego okresu">II</td>
    <td title="Średnia roczna">Śr.R</td>
    <td title="Przewidywana ocena roczna">(R)</td>
    <td title="Ocena roczna">R</td>
  </tr>
</thead>
<tr class="line0">
  <td class="center micro screen-only"><img src="/images/tree.png"/></td>
  <td>Historia</td>
  <td>6 4 [ 4 5 ] 4 5</td><td></td><td>5</td><td>5</td>
  <td>5 6 [ 1 5 ] 4 5</td><td></td><td>-</td><td></td>
  <td>5</td><td>-</td>
</tr>
<tr class="line1">
  <td class="center micro screen-only"></td>
  <td>Plastyka</td>
  <td>5 6</td><td></td><td>5</td><td>5</td>
  <td>6 6</td><td></td><td>-</td><td></td>
  <td>6</td><td>6</td>
</tr>
<tr class="line0">
  <td class="center micro screen-only"></td>
  <td>Etyka</td>
  <td></td><td></td><td>-</td><td>-</td>
  <td></td><td></td><td>-</td><td></td>
  <td>-</td><td>-</td>
</tr>
<tr class="line1">
  <td></td><td>Ocena</td><td>Nauczyciel</td><td>Brak ocen</td>
  <td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td>
</tr>
</table>
</body></html>
"""

FINAL_GRADES_NO_HEADER_HTML = """
<html><body>
<table class="decorated stretch">
<tr class="line0"><td></td><td>Historia</td><td>5</td></tr>
</table>
</body></html>
"""


class TestParseFinalGrades:
    def test_extracts_midterm_predicted_and_final(self):
        from src.scraping import FinalGrade, parse_final_grades

        grades = parse_final_grades(FINAL_GRADES_HTML)
        assert FinalGrade("Historia", "5", "5", "-") in grades
        assert FinalGrade("Plastyka", "5", "6", "6") in grades

    def test_subjects_without_grades_are_kept_with_dashes(self):
        from src.scraping import parse_final_grades

        grades = parse_final_grades(FINAL_GRADES_HTML)
        etyka = next(g for g in grades if g.subject == "Etyka")
        assert etyka.predicted_final == "-"
        assert etyka.final == "-"

    def test_noise_rows_are_filtered(self):
        from src.scraping import parse_final_grades

        grades = parse_final_grades(FINAL_GRADES_HTML)
        assert all(g.subject != "Ocena" for g in grades)
        assert len(grades) == 3

    def test_missing_header_titles_raise(self):
        """Layout drift must fail loudly, not return an empty list."""
        from src.scraping import parse_final_grades

        with pytest.raises(ParseError, match="header"):
            parse_final_grades(FINAL_GRADES_NO_HEADER_HTML)

    def test_empty_html_raises(self):
        from src.scraping import parse_final_grades

        with pytest.raises(ParseError, match="empty"):
            parse_final_grades("")

    def test_grade_row_limit_boundary(self):
        from src.scraping import parse_final_grades

        def grades_html(row_count):
            rows = "".join(
                f'<tr class="line0"><td></td><td>Subject {index}</td><td>5</td></tr>'
                for index in range(row_count)
            )
            return (
                '<table class="decorated stretch"><thead><tr>'
                '<td title="Ocena roczna">R</td></tr></thead>'
                f"{rows}</table>"
            )

        assert len(parse_final_grades(grades_html(200))) == 200
        with pytest.raises(ParseError, match="row count"):
            parse_final_grades(grades_html(201))


# Preschool layout (captured live): titled header WITHOUT the predicted column.
FINAL_GRADES_NO_PREDICTED_HTML = """
<html><body>
<table class="decorated stretch">
<thead>
  <tr>
    <td>Oceny bieżące</td>
    <td title="Ocena śródroczna z pierwszego okresu">I</td>
    <td>Oceny bieżące</td>
    <td title="Ocena śródroczna z drugiego okresu">II</td>
    <td title="Ocena roczna">R</td>
  </tr>
</thead>
<tr class="line0">
  <td></td><td>Religia</td>
  <td></td><td>-</td><td></td><td>-</td><td>5</td>
</tr>
</table>
</body></html>
"""


class TestParseFinalGradesVariants:
    def test_layout_without_predicted_column_defaults_to_dash(self):
        from src.scraping import parse_final_grades

        grades = parse_final_grades(FINAL_GRADES_NO_PREDICTED_HTML)
        assert len(grades) == 1
        assert grades[0].subject == "Religia"
        assert grades[0].midterm == "-"
        assert grades[0].predicted_final == "-"  # column absent in this layout
        assert grades[0].final == "5"

    def test_rows_outside_grades_table_are_ignored(self):
        from src.scraping import parse_final_grades

        # Prepend an unrelated line0 table (like the filter table on real pages).
        html = FINAL_GRADES_HTML.replace(
            '<table class="decorated stretch">',
            '<table class="decorated stretch"><tr class="line0">'
            "<td></td><td>FilterNoise</td><td></td><td></td><td></td><td></td>"
            "<td></td><td></td><td></td><td></td><td></td><td></td></tr></table>"
            '<table class="decorated stretch">',
            1,
        )
        grades = parse_final_grades(html)
        assert all(g.subject != "FilterNoise" for g in grades)

    def test_nested_table_rows_are_ignored(self):
        """Expanded grade details render as nested tables reusing line0/line1
        classes; their rows must not become fake subjects."""
        from src.scraping import parse_final_grades

        nested = (
            '<tr class="line0"><td></td><td><table class="decorated">'
            '<tr class="line1"><td>Kategoria</td><td>Komentarz</td><td>Oceny</td>'
            "<td>Data</td><td>x</td><td>x</td><td>x</td><td>x</td><td>x</td>"
            "<td>x</td><td>x</td><td>x</td></tr></table></td>"
            "<td></td><td></td><td></td><td></td><td></td><td></td><td></td>"
            "<td></td><td></td><td></td></tr>"
        )
        html = FINAL_GRADES_HTML.replace("</table>", nested + "</table>", 1)
        grades = parse_final_grades(html)
        assert all("Kategoria" not in g.subject for g in grades)

    def test_colspan_before_titled_header_cell_shifts_mapping(self):
        """A spanning header cell occupies N body columns; index mapping must
        sum colspans, not enumerate cells."""
        from src.scraping import parse_final_grades

        html = """
        <html><body><table class="decorated stretch">
        <thead><tr>
          <td colspan="2">Oceny</td>
          <td title="Ocena roczna">R</td>
        </tr></thead>
        <tr class="line0">
          <td></td><td>Historia</td><td>g1</td><td>g2</td><td>5</td>
        </tr>
        </table></body></html>
        """
        grades = parse_final_grades(html)
        assert len(grades) == 1
        assert grades[0].final == "5"  # body index 4, not enumerate index 1 + 2

    def test_br_wrapped_matched_title_still_matches(self):
        from src.scraping import parse_final_grades

        html = FINAL_GRADES_HTML.replace('title="Ocena roczna"', 'title="Ocena roczna<br> 2025/26"')
        grades = parse_final_grades(html)
        assert any(g.final == "6" for g in grades)  # Plastyka still parsed

    def test_colspan_in_grade_row_raises(self):
        """Body-side alignment contract: one td per column. A spanning cell in
        a parsed row must fail loudly, not shift values silently."""
        from src.scraping import parse_final_grades

        html = FINAL_GRADES_HTML.replace("<td>Plastyka</td>", '<td colspan="2">Plastyka</td>', 1)
        with pytest.raises(ParseError, match="colspan"):
            parse_final_grades(html)

    def test_short_subject_row_does_not_return_partial_grades(self):
        html = FINAL_GRADES_HTML.replace(
            "<td>Plastyka</td>",
            '<td>Plastyka</td></tr><tr class="line0"><td></td><td>Noise</td>',
            1,
        )

        with pytest.raises(ParseError, match="shorter than its header"):
            parse_final_grades(html)

    def test_grade_subject_is_trimmed(self):
        html = FINAL_GRADES_HTML.replace("<td>Plastyka</td>", "<td>  Plastyka  </td>", 1)

        assert any(grade.subject == "Plastyka" for grade in parse_final_grades(html))

    @pytest.mark.parametrize(
        "row",
        [
            '<tr class="line0"><td></td></tr>',
            '<tr class="line0"><td></td><td>Historia</td></tr>',
        ],
    )
    def test_grade_rows_at_short_boundaries_raise_parse_error(self, row):
        html = (
            '<table class="decorated stretch"><thead><tr>'
            '<td title="Ocena roczna">R</td></tr></thead>'
            f"{row}</table>"
        )

        with pytest.raises(ParseError):
            parse_final_grades(html)

    def test_non_numeric_header_colspan_raises(self):
        html = FINAL_GRADES_HTML.replace('colspan="2"', 'colspan="many"', 1)

        with pytest.raises(ParseError, match="non-numeric colspan"):
            parse_final_grades(html)

    @pytest.mark.parametrize("span", ["0", "100", "9" * 5000])
    def test_out_of_bounds_header_colspan_raises(self, span):
        html = FINAL_GRADES_HTML.replace('colspan="2"', f'colspan="{span}"', 1)

        with pytest.raises(ParseError, match="colspan"):
            parse_final_grades(html)

    def test_grade_column_limit_is_inclusive(self):
        html = """
        <table class="decorated stretch">
          <thead><tr><td title="Ocena roczna" colspan="98">R</td></tr></thead>
          <tr class="line0"><td></td><td>Historia</td><td>5</td></tr>
        </table>
        """

        assert parse_final_grades(html)[0].final == "5"
