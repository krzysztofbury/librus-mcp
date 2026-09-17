"""Own Synergia scraping for features librus-apix does not cover:
message attachments (download) and behaviour notes (uwagi).

Attachment flow (verified live 2026-06-11):
  GET  {BASE_URL}/wiadomosci/pobierz_zalacznik/{message_id}/{file_id}
       -> 302 redirect to https://sandbox.librus.pl/GetFile/<key>
  GET  <redirect url>/get
       -> file bytes with Content-Disposition filename

The redirect is followed manually: the first request carries session cookies
and must not follow an attacker-controllable Location; the sandbox URL is a
signed key, so the actual download is made with no cookies at all.

Uwagi page layout was captured live only in its empty state ("Brak uwag");
the populated parser handles both Synergia table shapes (label-pair detail
tables and column tables) and may need adjustment against a real note.
"""

import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.parse import urlparse
from uuid import uuid4

import requests
from bs4 import BeautifulSoup, Tag
from librus_apix import urls as librus_urls
from librus_apix.client import Client
from librus_apix.exceptions import ParseError, TokenError
from librus_apix.helpers import no_access_check
from requests.cookies import RequestsCookieJar

# Matches both raw and JS-escaped hrefs: /wiadomosci/pobierz_zalacznik/123/456
ATTACHMENT_PATTERN = re.compile(r"pobierz_zalacznik(?:\\/|/)(\d+)(?:\\/|/)(\d+)")
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 20
MAX_FINAL_GRADE_COLUMNS = 100
DOWNLOAD_HOST = "sandbox.librus.pl"
DOWNLOAD_PATH_PREFIX = "/GetFile/"
REQUEST_TIMEOUT_SECONDS = 30.0
DOWNLOAD_DEADLINE_SECONDS = 120.0
DOWNLOAD_CHUNK_BYTES = 64 * 1024
MAX_FILENAME_ATTEMPTS = 100

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


class AttachmentDownloadCancelled(Exception):
    """Stop a worker after its async caller is cancelled or timed out."""


@dataclass
class DownloadCancellation:
    _cancelled: Event = dataclass_field(default_factory=Event)
    _publication_lock: Lock = dataclass_field(default_factory=Lock)
    _abort_lock: Lock = dataclass_field(default_factory=Lock)
    _abort: Callable[[], None] | None = None

    def cancel(self) -> None:
        with self._abort_lock:
            if self._cancelled.is_set():
                return
            self._cancelled.set()
            abort = self._abort
        if abort is not None:
            Thread(
                target=self._abort_safely,
                args=(abort,),
                name="librus-attachment-abort",
                daemon=True,
            ).start()

    def publication_is_idle(self) -> bool:
        acquired = self._publication_lock.acquire(blocking=False)
        if acquired:
            self._publication_lock.release()
        return acquired

    def set_abort(self, abort: Callable[[], None]) -> None:
        with self._abort_lock:
            if not self._cancelled.is_set():
                self._abort = abort
                return
        self._abort_safely(abort)

    def clear_abort(self) -> None:
        with self._abort_lock:
            self._abort = None

    @staticmethod
    def _abort_safely(abort: Callable[[], None]) -> None:
        try:
            abort()
        except (OSError, requests.RequestException) as error:
            print(f"librus-mcp: attachment response abort failed: {error}", file=sys.stderr)

    def raise_if_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise AttachmentDownloadCancelled("attachment download was cancelled")


def parse_attachments(html: str) -> list[Attachment]:
    """Extract attachment entries from a message detail page."""
    if not html.strip():
        raise ParseError("attachment page HTML is empty")
    return _parse_attachments_soup(BeautifulSoup(html, "lxml"))


def _parse_attachments_soup(soup: BeautifulSoup) -> list[Attachment]:
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
    if len(attachments) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise ValueError(f"implausible attachment count: {len(attachments)}")
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
    _require_bare_id(message_id, "message_id")
    response = client.get(client.MESSAGE_URL + "/" + message_id)
    if not response.text.strip():
        raise ParseError("attachment page HTML is empty")
    soup = BeautifulSoup(response.text, "lxml")
    no_access_check(soup)
    return _parse_attachments_soup(soup)


def download_attachment(
    client: Client,
    message_id: str,
    file_id: str,
    download_dir: Path,
    cancellation: DownloadCancellation | None = None,
) -> dict:
    """Download one attachment to download_dir. Returns path/filename/size/content_type."""
    _require_bare_id(message_id, "message_id")
    _require_bare_id(file_id, "file_id")
    cancellation = cancellation or DownloadCancellation()
    cancellation.raise_if_cancelled()

    url = f"{client.BASE_URL}/wiadomosci/pobierz_zalacznik/{message_id}/{file_id}"
    download_url = _resolve_download_url(client, url)
    cancellation.raise_if_cancelled()
    fallback_filename = f"attachment_{message_id}_{file_id}"
    return _stream_attachment(
        download_url, client.proxy, download_dir, fallback_filename, cancellation
    )


def _require_bare_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.isdigit():
        raise ValueError(f"{name} must be a numeric ID, got: '{value}'")


def _resolve_download_url(client: Client, url: str) -> str:
    """Request the attachment endpoint without following redirects and return
    the validated sandbox download URL. The authenticated request must not
    follow an arbitrary Location: the client's auth cookies are domainless and
    would be sent to whatever host the redirect names."""
    cookie_jar = RequestsCookieJar()
    cookie_jar.update(client.cookies)
    cookie_jar.update(client.token.access_cookies())
    response = requests.get(
        url,
        headers=librus_urls.HEADERS,
        cookies=cookie_jar,
        allow_redirects=False,
        timeout=REQUEST_TIMEOUT_SECONDS,
        proxies=client.proxy,
    )
    # An expired session redirects to the login page instead of the sandbox;
    # TokenError lets the manager's retry re-authenticate once.
    if response.status_code != 302:
        raise TokenError(f"attachment request did not redirect (HTTP {response.status_code})")
    location = response.headers.get("Location", "")
    parsed = urlparse(location)
    is_sandbox = (
        parsed.scheme == "https"
        and parsed.hostname == DOWNLOAD_HOST
        and parsed.port in (None, 443)
        and parsed.path.startswith(DOWNLOAD_PATH_PREFIX)
        and not parsed.query
        and not parsed.fragment
    )
    if not is_sandbox:
        raise TokenError(f"unexpected attachment redirect target: '{location}'")
    return location


def _stream_attachment(
    download_url: str,
    proxy: dict,
    download_dir: Path,
    fallback_filename: str,
    cancellation: DownloadCancellation,
) -> dict:
    """Stream a signed sandbox download directly to an exclusive local file."""
    deadline = time.monotonic() + DOWNLOAD_DEADLINE_SECONDS
    received_bytes = 0
    temporary_path: Path | None = None
    try:
        cancellation.raise_if_cancelled()
        with requests.get(
            download_url + "/get",
            headers={**librus_urls.HEADERS, "Accept-Encoding": "identity"},
            stream=True,
            allow_redirects=False,
            timeout=REQUEST_TIMEOUT_SECONDS,
            proxies=proxy,
        ) as response:
            try:
                cancellation.set_abort(response.close)
                if response.status_code != 200:
                    raise ValueError(f"attachment download failed: HTTP {response.status_code}")
                content_type = response.headers.get("Content-Type", "")
                disposition = response.headers.get("Content-Disposition", "")
                content_length = response.headers.get("Content-Length", "")
                content_encoding = response.headers.get("Content-Encoding", "identity").lower()
                if content_encoding not in ("", "identity"):
                    raise ValueError(f"unsupported attachment content encoding: {content_encoding}")
                if content_length.isdigit() and int(content_length) > MAX_ATTACHMENT_BYTES:
                    raise ValueError(f"attachment exceeds the {MAX_ATTACHMENT_BYTES} byte limit")
                filename = _safe_attachment_filename(disposition, fallback_filename)
                cancellation.raise_if_cancelled()
                temporary_path, descriptor = _create_temporary_file(download_dir)
                try:
                    handle = os.fdopen(descriptor, "wb")
                except BaseException:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                    raise
                with handle:
                    received_bytes = _write_attachment_chunks(
                        response, handle, deadline, cancellation
                    )
                if not received_bytes:
                    raise ValueError("attachment download returned an empty body")
            finally:
                cancellation.clear_abort()
        target_path = _publish_unique_file(temporary_path, filename, cancellation)
    except BaseException:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                print(
                    f"librus-mcp: attachment temporary file cleanup failed: {cleanup_error}",
                    file=sys.stderr,
                )
        raise
    return {
        "path": str(target_path),
        "filename": target_path.name,
        "size": received_bytes,
        "content_type": content_type,
    }


def _safe_attachment_filename(disposition: str, fallback_filename: str) -> str:
    # Path(...).name strips directories but passes dot components through.
    filename = Path(_filename_from_disposition(disposition)).name.strip()
    return fallback_filename if filename in ("", ".", "..") else filename


def _create_temporary_file(download_dir: Path) -> tuple[Path, int]:
    """Open an exclusive temporary file in the destination filesystem."""
    download_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = download_dir / f".librus-mcp-{os.getpid()}-{uuid4().hex}.tmp"
    open_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary_path, open_flags, 0o600)
    return temporary_path, descriptor


def _write_attachment_chunks(
    response, handle, deadline: float, cancellation: DownloadCancellation
) -> int:
    received_bytes = 0
    for chunk in _iter_attachment_chunks(response, deadline, cancellation):
        if not chunk:
            continue
        received_bytes += len(chunk)
        if received_bytes > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"attachment exceeds the {MAX_ATTACHMENT_BYTES} byte limit")
        handle.write(chunk)
    return received_bytes


def _iter_attachment_chunks(response, deadline: float, cancellation: DownloadCancellation):
    raw = getattr(response, "raw", None)
    if raw is not None and hasattr(raw, "read1"):
        # read1 returns available bytes instead of buffering until 64 KiB is full.
        def read_chunk():
            return raw.read1(DOWNLOAD_CHUNK_BYTES, decode_content=False)

    else:
        chunks = iter(response.iter_content(DOWNLOAD_CHUNK_BYTES))

        def read_chunk():
            return next(chunks, b"")

    while True:
        cancellation.raise_if_cancelled()
        if time.monotonic() >= deadline:
            raise ValueError("attachment download exceeded its deadline")
        chunk = read_chunk()
        cancellation.raise_if_cancelled()
        if time.monotonic() >= deadline:
            raise ValueError("attachment download exceeded its deadline")
        if not chunk:
            return
        yield chunk


def _publish_unique_file(
    temporary_path: Path, filename: str, cancellation: DownloadCancellation
) -> Path:
    """Atomically publish a complete file without overwriting an existing path."""
    assert filename not in ("", ".", ".."), "filename must not be empty or a dot component"
    assert filename == Path(filename).name, "filename must be bare, with no path components"
    with cancellation._publication_lock:
        cancellation.raise_if_cancelled()
        download_dir = temporary_path.parent
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        for attempt in range(MAX_FILENAME_ATTEMPTS):
            candidate = filename if attempt == 0 else f"{stem} ({attempt}){suffix}"
            target_path = download_dir / candidate
            try:
                os.link(temporary_path, target_path, follow_symlinks=False)
            except FileExistsError:
                continue
            except OSError as error:
                raise ValueError(
                    f"attachment cannot be published atomically in '{download_dir}'; "
                    "the filesystem must support hard links"
                ) from error
            try:
                temporary_path.unlink()
            except OSError as error:
                print(
                    f"librus-mcp: attachment saved at {target_path}, but temporary "
                    f"file cleanup failed: {error}",
                    file=sys.stderr,
                )
            return target_path
    raise ValueError(f"no unique filename for '{filename}' after {MAX_FILENAME_ATTEMPTS} attempts")


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
    if not html:
        raise ParseError("behaviour-notes page HTML is empty")
    return _parse_behaviour_notes_soup(BeautifulSoup(html, "lxml"))


def _parse_behaviour_notes_soup(soup: BeautifulSoup) -> list[BehaviourNote]:
    empty_marker = soup.select_one("p.msgEmptyTable")
    if empty_marker is not None and "Brak uwag" in empty_marker.get_text():
        return []
    notes: list[BehaviourNote] = []
    for table in soup.select("table.decorated"):
        notes.extend(_notes_from_table(table))
    if not notes:
        raise ParseError("unrecognized uwagi page layout: no empty marker and no parseable notes")
    return notes


def get_behaviour_notes(client: Client) -> list[BehaviourNote]:
    """Fetch and parse the behaviour notes (uwagi) page."""
    response = client.get(client.BASE_URL + "/uwagi")
    soup = BeautifulSoup(response.text, "lxml")
    no_access_check(soup)
    return _parse_behaviour_notes_soup(soup)


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
    for row in table.find_all("tr", recursive=False):
        cells = row.find_all("td", recursive=False)
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
    for row in body.find_all("tr", recursive=False):
        cells = row.find_all("td", recursive=False)
        fields: dict[str, str] = {}
        try:
            for field, cell in zip(columns, cells, strict=True):
                if field is not None:
                    fields[field] = cell.get_text(strip=True)
        except ValueError as error:
            raise ParseError("behaviour note row does not match its header") from error
        if fields:
            notes.append(_note_from_fields(fields))
    return notes


def _note_from_fields(fields: dict[str, str]) -> BehaviourNote:
    missing_fields = [field for field in ("date", "content") if not fields.get(field)]
    if missing_fields:
        raise ParseError(f"behaviour note is missing required fields: {', '.join(missing_fields)}")
    return BehaviourNote(
        date=fields["date"],
        teacher=fields.get("teacher", ""),
        category=fields.get("category", ""),
        content=fields["content"],
    )


@dataclass
class FinalGrade:
    """End-of-year grade summary row: midterm (I), predicted annual (R), annual."""

    subject: str
    midterm: str
    predicted_final: str
    final: str


_FINAL_GRADE_HEADER_TITLES = {
    "Ocena śródroczna z pierwszego okresu": "midterm",
    "Przewidywana ocena roczna": "predicted_final",
    "Ocena roczna": "final",
}
# Header cells skip the checkbox and subject columns present in body rows.
_HEADER_TO_BODY_OFFSET = 2


def parse_final_grades(html: str) -> list[FinalGrade]:
    """Parse the grades page summary columns librus-apix ignores:
    (I) midterm, (R) predicted annual, R annual.

    Column sets vary by account type (preschool pages lack the predicted
    column), so fields map to '-' when their column is absent. A page with
    no annual-grade column at all fails loudly: that is layout drift or the
    wrong page, not an account variant seen so far.
    """
    if not html:
        raise ParseError("grades page HTML is empty")
    return _parse_final_grades_soup(BeautifulSoup(html, "lxml"))


def _parse_final_grades_soup(soup: BeautifulSoup) -> list[FinalGrade]:
    located = _locate_final_grades_table(soup)
    if located is None:
        raise ParseError("grades page header not recognized (no annual grade column)")
    table, column_map = located

    # Expanded grade details nest whole tables inside rows, reusing the
    # line0/line1 classes; count and parse only rows belonging directly
    # to the grades table.
    rows = [
        row
        for row in table.find_all("tr", attrs={"class": ["line0", "line1"]})
        if row.find_parent("table") is table
    ]
    if len(rows) > 200:
        raise ParseError(f"implausible grade row count: {len(rows)}")
    grades: list[FinalGrade] = []
    for row in rows:
        grade = _final_grade_from_row(row, table, column_map)
        if grade is not None:
            grades.append(grade)
    # A recognized grades table that yields zero rows means the row filters
    # drifted, not that the student has no subjects: the table always lists
    # subjects even when every grade cell is '-'.
    if not grades:
        raise ParseError("grades table recognized but no rows parsed")
    return grades


def _final_grade_from_row(row: Tag, table: Tag, column_map: dict[str, int]) -> FinalGrade | None:
    """Extract one FinalGrade from a table row; None for non-subject rows."""
    assert row.find_parent("table") is table, "row must belong directly to the grades table"
    # Rows wrapping a nested detail table carry no subject of their own.
    if row.find("table") is not None:
        return None
    cells = row.find_all("td", recursive=False)
    if len(cells) < 2:
        return None
    # Subject is always the second body cell (after the expand checkbox).
    subject = cells[1].get_text(" ", strip=True)
    # Nested detail tables repeat 'Ocena'/'Nauczyciel' label rows; skip them.
    if not subject or subject == "Ocena":
        return None
    if len(cells) <= max(column_map.values()):
        raise ParseError(f"grade row for {subject!r} is shorter than its header")
    # Column mapping assumes one td per body column; a spanning cell would
    # silently shift every value past it.
    if any(cell.has_attr("colspan") for cell in cells):
        raise ParseError("unexpected colspan in grade row")
    values = {field: cells[index].get_text(" ", strip=True) for field, index in column_map.items()}
    return FinalGrade(
        subject=subject,
        midterm=values.get("midterm", "-"),
        predicted_final=values.get("predicted_final", "-"),
        final=values.get("final", "-"),
    )


def _locate_final_grades_table(soup: BeautifulSoup) -> tuple[Tag, dict[str, int]] | None:
    """Find the grades table by its titled header cells and map FinalGrade
    fields to body-row cell indexes. The annual grade column is required;
    other columns are optional account-type variants."""
    for table in soup.select("table.decorated.stretch"):
        thead = table.find("thead")
        if thead is None:
            continue
        for row in thead.find_all("tr"):
            column_map: dict[str, int] = {}
            # A header cell with colspan=N occupies N body columns; sum spans
            # instead of enumerating cells, or the mapping silently shifts.
            body_column = _HEADER_TO_BODY_OFFSET
            for cell in row.find_all("td"):
                title = cell.get("title", "").split("<br>")[0].strip()
                field = _FINAL_GRADE_HEADER_TITLES.get(title)
                if field is not None:
                    column_map[field] = body_column
                span = cell.get("colspan", "1")
                try:
                    span_value = int(str(span))
                except ValueError:
                    raise ParseError(f"non-numeric colspan: {span!r}")
                if span_value < 1 or body_column + span_value > MAX_FINAL_GRADE_COLUMNS:
                    raise ParseError(f"grade header colspan is out of bounds: {span!r}")
                body_column += span_value
            if "final" in column_map:
                return table, column_map
    return None


def get_final_grades(client: Client) -> list[FinalGrade]:
    """Fetch and parse end-of-year grade columns from the grades page."""
    response = client.get(client.GRADES_URL)
    soup = BeautifulSoup(response.text, "lxml")
    no_access_check(soup)
    return _parse_final_grades_soup(soup)
