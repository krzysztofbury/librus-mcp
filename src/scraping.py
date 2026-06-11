"""Own Synergia scraping for features librus-apix does not cover:
message attachments (download) and behaviour notes (uwagi).

Attachment flow (verified live 2026-06-11):
  GET  {BASE_URL}/wiadomosci/pobierz_zalacznik/{message_id}/{file_id}
       -> 302 redirect to https://sandbox.librus.pl/GetFile/<key>
  GET  <redirect url>/get
       -> file bytes with Content-Disposition filename

Uwagi page layout was captured live only in its empty state ("Brak uwag");
the populated parser handles both Synergia table shapes (label-pair detail
tables and column tables) and may need adjustment against a real note.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from librus_apix.client import Client
from librus_apix.helpers import no_access_check

# Matches both raw and JS-escaped hrefs: /wiadomosci/pobierz_zalacznik/123/456
ATTACHMENT_PATTERN = re.compile(r"pobierz_zalacznik(?:\\/|/)(\d+)(?:\\/|/)(\d+)")
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 20

_LABEL_FIELD_MAP = {
    "data": "date",
    "nauczyciel": "teacher",
    "rodzaj": "category",
    "treść": "content",
    "uwaga": "content",
}


@dataclass
class Attachment:
    filename: str
    message_id: str
    file_id: str


@dataclass
class BehaviourNote:
    date: str
    teacher: str
    category: str
    content: str


def resolve_download_dir(config_download_dir: str | None) -> Path:
    """Resolve download dir. Priority: LIBRUS_DOWNLOAD_DIR env > config > default."""
    if "LIBRUS_DOWNLOAD_DIR" in os.environ:
        return Path(os.environ["LIBRUS_DOWNLOAD_DIR"]).expanduser()
    if config_download_dir:
        return Path(config_download_dir).expanduser()
    return Path.home() / ".librus-mcp" / "downloads"


def parse_attachments(html: str) -> list[Attachment]:
    """Extract attachment entries from a message detail page."""
    assert html, "html must not be empty"
    soup = BeautifulSoup(html, "lxml")
    attachments: list[Attachment] = []
    for img in soup.find_all("img", onclick=True):
        match = ATTACHMENT_PATTERN.search(img.get("onclick", ""))
        if match is None:
            continue
        message_id = match.group(1)
        file_id = match.group(2)
        attachments.append(
            Attachment(_attachment_filename(img, message_id, file_id), message_id, file_id)
        )
    assert len(attachments) <= MAX_ATTACHMENTS_PER_MESSAGE, "implausible attachment count"
    return attachments


def _attachment_filename(download_img: Tag, message_id: str, file_id: str) -> str:
    """The filename lives in the first cell of the row holding the download icon."""
    row = download_img.find_parent("tr")
    if row is not None:
        name_cell = row.find("td")
        if name_cell is not None:
            filename = name_cell.get_text(strip=True)
            if filename:
                return filename
    return f"attachment_{message_id}_{file_id}"


def get_attachments(client: Client, message_id: str) -> list[Attachment]:
    """Fetch the message detail page and list its attachments."""
    assert message_id, "message_id must not be empty"
    assert "/" not in message_id, "message_id must be a bare ID"
    response = client.get(client.MESSAGE_URL + "/" + message_id)
    no_access_check(BeautifulSoup(response.text, "lxml"))
    return parse_attachments(response.text)


def download_attachment(client: Client, message_id: str, file_id: str, download_dir: Path) -> dict:
    """Download one attachment to download_dir. Returns path/filename/size/content_type.

    Relies on Client.get following redirects (the requests default): the first
    GET returns the *followed* sandbox.librus.pl/GetFile/<key> page, and the
    file bytes live at <key>/get.
    """
    assert message_id, "message_id must not be empty"
    assert file_id, "file_id must not be empty"
    assert "/" not in message_id, "message_id must be a bare ID"
    assert "/" not in file_id, "file_id must be a bare ID"

    url = f"{client.BASE_URL}/wiadomosci/pobierz_zalacznik/{message_id}/{file_id}"
    landing_response = client.get(url)
    assert landing_response.status_code == 200, (
        f"attachment redirect failed: {landing_response.status_code}"
    )
    assert "/GetFile/" in landing_response.url, (
        f"unexpected download redirect target: {landing_response.url}"
    )

    response = client.get(landing_response.url + "/get")
    assert response.status_code == 200, f"attachment download failed: {response.status_code}"
    content = response.content
    assert len(content) > 0, "attachment download returned empty body"
    assert len(content) <= MAX_ATTACHMENT_BYTES, f"attachment too large: {len(content)} bytes"

    filename = _filename_from_disposition(response.headers.get("Content-Disposition", ""))
    if not filename:
        filename = f"attachment_{message_id}_{file_id}"
    # Strip any path components so the server-supplied name cannot escape download_dir.
    filename = Path(filename).name

    download_dir.mkdir(parents=True, exist_ok=True)
    target_path = download_dir / filename
    target_path.write_bytes(content)
    return {
        "path": str(target_path),
        "filename": filename,
        "size": len(content),
        "content_type": response.headers.get("Content-Type", ""),
    }


def _filename_from_disposition(disposition: str) -> str:
    match = re.search(r'filename="?([^";]+)"?', disposition)
    if match is None:
        return ""
    return match.group(1).strip()


def parse_behaviour_notes(html: str) -> list[BehaviourNote]:
    """Parse the /uwagi page into behaviour notes.

    The only trustworthy empty signal is the explicit "Brak uwag" marker.
    Anything else that yields zero notes means the layout is unrecognized —
    failing loudly beats a false "no behaviour notes" for a parent.
    """
    assert html, "html must not be empty"
    soup = BeautifulSoup(html, "lxml")
    empty_marker = soup.select_one("p.msgEmptyTable")
    if empty_marker is not None and "Brak uwag" in empty_marker.get_text():
        return []
    notes: list[BehaviourNote] = []
    for table in soup.select("table.decorated"):
        notes.extend(_notes_from_table(table))
    assert notes, "unrecognized uwagi page layout: no empty marker and no parseable notes"
    return notes


def get_behaviour_notes(client: Client) -> list[BehaviourNote]:
    """Fetch and parse the behaviour notes (uwagi) page."""
    response = client.get(client.BASE_URL + "/uwagi")
    no_access_check(BeautifulSoup(response.text, "lxml"))
    return parse_behaviour_notes(response.text)


def _field_for_label(label: str) -> str | None:
    normalized = label.strip().lower()
    for prefix, field in _LABEL_FIELD_MAP.items():
        if normalized.startswith(prefix):
            return field
    return None


def _notes_from_table(table: Tag) -> list[BehaviourNote]:
    thead = table.find("thead")
    if thead is not None:
        return _notes_from_column_table(table, thead)
    return _notes_from_label_pairs(table)


def _notes_from_label_pairs(table: Tag) -> list[BehaviourNote]:
    """One detail table = one note: rows of (label, value) cell pairs."""
    fields: dict[str, str] = {}
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 2:
            continue
        field = _field_for_label(cells[0].get_text(strip=True))
        if field is None:
            continue
        fields[field] = cells[1].get_text(strip=True)
    if not fields:
        return []
    return [_note_from_fields(fields)]


def _notes_from_column_table(table: Tag, thead: Tag) -> list[BehaviourNote]:
    """One list table = many notes: header row maps columns to fields."""
    headers = [cell.get_text(strip=True) for cell in thead.find_all(["td", "th"])]
    columns = [_field_for_label(header) for header in headers]
    body = table.find("tbody")
    if body is None:
        body = table
    notes: list[BehaviourNote] = []
    for row in body.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != len(columns):
            continue
        fields: dict[str, str] = {}
        for field, cell in zip(columns, cells):
            if field is not None:
                fields[field] = cell.get_text(strip=True)
        if fields:
            notes.append(_note_from_fields(fields))
    return notes


def _note_from_fields(fields: dict[str, str]) -> BehaviourNote:
    return BehaviourNote(
        date=fields.get("date", ""),
        teacher=fields.get("teacher", ""),
        category=fields.get("category", ""),
        content=fields.get("content", ""),
    )
