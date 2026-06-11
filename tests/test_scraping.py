"""Tests for own-scraping additions: message attachments and behaviour notes (uwagi).

Fixture HTML mirrors real Synergia markup captured on 2026-06-11 (personal data
replaced with synthetic values).
"""

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


# --- download_attachment with a fake client ---


class FakeResponse:
    def __init__(self, status_code=200, url="", content=b"", headers=None):
        self.status_code = status_code
        self.url = url
        self.content = content
        self.headers = headers or {}


class FakeClient:
    BASE_URL = "https://synergia.librus.pl"

    def __init__(self, responses):
        self._responses = list(responses)
        self.requested_urls = []

    def get(self, url):
        self.requested_urls.append(url)
        return self._responses.pop(0)


class TestDownloadAttachment:
    def _client(self, filename='attachment; filename="raport.pdf"', content=b"%PDF-1.4 data"):
        redirect = FakeResponse(url="https://sandbox.librus.pl/GetFile/abc123")
        file_response = FakeResponse(
            content=content,
            headers={"Content-Disposition": filename, "Content-Type": "application/pdf"},
        )
        return FakeClient([redirect, file_response])

    def test_writes_file_and_returns_info(self, tmp_path):
        from src.scraping import download_attachment

        client = self._client()
        info = download_attachment(client, "1234567", "7654321", tmp_path)
        assert (tmp_path / "raport.pdf").read_bytes() == b"%PDF-1.4 data"
        assert info["filename"] == "raport.pdf"
        assert info["size"] == 13
        assert info["content_type"] == "application/pdf"
        # Second request must hit the redirect target with /get appended.
        assert client.requested_urls[1] == "https://sandbox.librus.pl/GetFile/abc123/get"

    def test_path_traversal_in_filename_is_stripped(self, tmp_path):
        from src.scraping import download_attachment

        client = self._client(filename='attachment; filename="../../evil.sh"')
        info = download_attachment(client, "1", "2", tmp_path)
        assert info["filename"] == "evil.sh"
        assert (tmp_path / "evil.sh").exists()
        assert not (tmp_path.parent / "evil.sh").exists()

    def test_missing_disposition_falls_back_to_ids(self, tmp_path):
        from src.scraping import download_attachment

        redirect = FakeResponse(url="https://sandbox.librus.pl/GetFile/abc123")
        file_response = FakeResponse(content=b"data", headers={})
        client = FakeClient([redirect, file_response])
        info = download_attachment(client, "11", "22", tmp_path)
        assert info["filename"] == "attachment_11_22"

    def test_unexpected_redirect_target_raises(self, tmp_path):
        from src.scraping import download_attachment

        redirect = FakeResponse(url="https://synergia.librus.pl/uczen/index")
        client = FakeClient([redirect])
        with pytest.raises(AssertionError, match="redirect"):
            download_attachment(client, "1", "2", tmp_path)

    def test_empty_body_raises(self, tmp_path):
        from src.scraping import download_attachment

        client = self._client(content=b"")
        with pytest.raises(AssertionError, match="empty"):
            download_attachment(client, "1", "2", tmp_path)

    def test_slash_in_file_id_raises(self, tmp_path):
        from src.scraping import download_attachment

        with pytest.raises(AssertionError, match="bare ID"):
            download_attachment(FakeClient([]), "1", "2/3", tmp_path)


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
