"""Tests for own-scraping additions: message attachments and behaviour notes (uwagi).

Fixture HTML mirrors real Synergia markup captured on 2026-06-11 (personal data
replaced with synthetic values).
"""

from unittest.mock import patch

import pytest

from src.scraping import (
    Attachment,
    BehaviourNote,
    parse_attachments,
    parse_behaviour_notes,
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
        with pytest.raises(AssertionError):
            parse_attachments("")


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
        with pytest.raises(AssertionError):
            parse_behaviour_notes("")


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

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

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
        with patcher:
            with pytest.raises(OSError, match="response close failed"):
                download_attachment(FakeClient(), "1", "2", tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_unsupported_hard_links_raise_actionable_error(self, tmp_path):
        from src.scraping import download_attachment

        patcher, _ = _patch_http(self._responses())
        with patcher, patch("src.scraping.os.link", side_effect=OSError("not supported")):
            with pytest.raises(ValueError, match="filesystem must support hard links"):
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
        with patcher:
            with pytest.raises(TokenError, match="did not redirect"):
                download_attachment(FakeClient(), "1", "2", tmp_path)

    def test_redirect_to_foreign_host_raises(self, tmp_path):
        from librus_apix.exceptions import TokenError
        from src.scraping import download_attachment

        patcher, mock = _patch_http(
            [FakeRedirectResponse(location="https://evil.example/GetFile/abc123")]
        )
        with patcher:
            with pytest.raises(TokenError, match="unexpected attachment redirect"):
                download_attachment(FakeClient(), "1", "2", tmp_path)
        # The forged Location must never be requested.
        assert mock.call_count == 1

    def test_redirect_to_plain_http_raises(self, tmp_path):
        from librus_apix.exceptions import TokenError
        from src.scraping import download_attachment

        patcher, _ = _patch_http(
            [FakeRedirectResponse(location="http://sandbox.librus.pl/GetFile/abc123")]
        )
        with patcher:
            with pytest.raises(TokenError, match="unexpected attachment redirect"):
                download_attachment(FakeClient(), "1", "2", tmp_path)

    def test_redirect_with_odd_port_raises(self, tmp_path):
        from librus_apix.exceptions import TokenError
        from src.scraping import download_attachment

        patcher, _ = _patch_http(
            [FakeRedirectResponse(location="https://sandbox.librus.pl:8080/GetFile/abc123")]
        )
        with patcher:
            with pytest.raises(TokenError, match="unexpected attachment redirect"):
                download_attachment(FakeClient(), "1", "2", tmp_path)

    def test_redirect_with_query_raises(self, tmp_path):
        from librus_apix.exceptions import TokenError
        from src.scraping import download_attachment

        patcher, _ = _patch_http(
            [FakeRedirectResponse(location="https://sandbox.librus.pl/GetFile/abc?key=1")]
        )
        with patcher:
            with pytest.raises(TokenError, match="unexpected attachment redirect"):
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
        with patcher:
            with pytest.raises(ValueError, match="empty"):
                download_attachment(FakeClient(), "1", "2", tmp_path)

    def test_oversized_body_raises(self, tmp_path, monkeypatch):
        from src import scraping

        monkeypatch.setattr(scraping, "MAX_ATTACHMENT_BYTES", 8)
        patcher, _ = _patch_http(self._responses(content=b"0123456789"))
        with patcher:
            with pytest.raises(ValueError, match="byte limit"):
                scraping.download_attachment(FakeClient(), "1", "2", tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_oversized_content_length_fails_before_streaming(self, tmp_path, monkeypatch):
        from src import scraping

        monkeypatch.setattr(scraping, "MAX_ATTACHMENT_BYTES", 8)
        response = FakeStreamResponse(
            content=b"0123456789",
            headers={"Content-Length": "10", "Content-Disposition": 'filename="large.bin"'},
        )
        patcher, _ = _patch_http([FakeRedirectResponse(), response])
        with patcher:
            with pytest.raises(ValueError, match="byte limit"):
                scraping.download_attachment(FakeClient(), "1", "2", tmp_path)
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


class TestResolveDownloadDir:
    def test_tilde_is_expanded(self, monkeypatch):
        from src.scraping import resolve_download_dir

        monkeypatch.delenv("LIBRUS_DOWNLOAD_DIR", raising=False)
        result = resolve_download_dir("~/custom_downloads")
        assert "~" not in str(result)

    def test_env_var_wins(self, tmp_path, monkeypatch):
        from src.scraping import resolve_download_dir

        monkeypatch.setenv("LIBRUS_DOWNLOAD_DIR", str(tmp_path / "env_dl"))
        assert resolve_download_dir("/other") == tmp_path / "env_dl"


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
        with pytest.raises(AssertionError, match="unrecognized"):
            parse_behaviour_notes(UWAGI_UNRECOGNIZED_HTML)


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

        with pytest.raises(AssertionError, match="header"):
            parse_final_grades(FINAL_GRADES_NO_HEADER_HTML)

    def test_empty_html_raises(self):
        from src.scraping import parse_final_grades

        with pytest.raises(AssertionError):
            parse_final_grades("")


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
        with pytest.raises(AssertionError, match="colspan"):
            parse_final_grades(html)
