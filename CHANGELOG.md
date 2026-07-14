# Changelog

All notable changes to this project will be documented in this file.

## [0.6.0] - 2026-07-14

### Security
- `send_message` never retries an authentication failure after its POST. A retry
  could duplicate a real school message, so the server instead reports an
  uncertain result and directs the caller to inspect the sent folder
- Attendance and homework detail references must now be bare numeric IDs from
  Librus, preventing a tool call from traversing to an arbitrary authenticated
  Synergia route
- Notification seen-state transactions now use an advisory file lock in
  addition to the existing in-process lock, preventing two MCP processes that
  share `state_dir` from re-reporting or losing updates

### Fixed
- `send_message` reports `status: "failed"` when Librus rejects delivery
- Every upstream requests-based call, including login, has a 30-second HTTP
  timeout; each upstream operation also has a 120-second deadline, quarantines
  its alias while a timed-out worker finishes, and retires its client

## [0.5.2] - 2026-07-14

### Added
- Per-alias login cooldown: after a failed authentication, further login attempts for that account are refused for 60 seconds and fail instantly with the original reason. Librus throttles the login endpoint per account; a caller retrying a failing tool in a loop would otherwise deepen the throttle (or, with bad credentials, risk a lockout). A successful login clears the cooldown

### Fixed
- A throttled Librus login (non-JSON response from the token endpoint) surfaced as raw JSON-parse noise (`Expecting value: line 1 column 1`); it now says login throttling is the likely cause and to wait a few minutes

## [0.5.1] - 2026-07-14

### Fixed
- `get_attendance_frequency` failed with a bare `KeyError` (e.g. `'4766'`) for schools that define custom attendance types — upstream librus-apix hardcodes the gateway attendance-type map. The error is now actionable and points to `get_subject_frequency`, which scrapes the frequency page and is unaffected

## [0.5.0] - 2026-07-14

Security- and safety-focused release based on a full code audit.

### Security
- **Cross-account cookie isolation**: upstream librus-apix creates every client with the same shared mutable cookie jar, so under concurrent calls one child's request could authenticate with another child's session cookies. Each client now gets its own cookie jar, and all requests for one alias are serialized by a per-alias lock (different aliases still run concurrently)
- **Attachment download hardening**: the authenticated redirect is no longer followed blindly — the `Location` must be exactly `https://sandbox.librus.pl/GetFile/…`; the file itself is fetched **without any cookies** (the signed URL alone authorizes it), streamed with a 50 MiB cap and a deadline, and written with `O_EXCL|O_NOFOLLOW` — never overwriting an existing file (collisions get a ` (n)` suffix) and never following symlinks
- **`send_message` two-step confirmation**: the first call sends nothing and returns a preview plus a single-use `confirm_token` (5-minute TTL, bound to the exact payload); only the second call with that token delivers. All tools now carry MCP `ToolAnnotations` — `send_message` is marked destructive/non-idempotent
- Untrusted inputs (MCP tool arguments, config) are validated with explicit `ValueError`s instead of `assert`, which Python strips under `-O`; message/file IDs must be numeric, detail URLs must be relative, and input schemas carry `Literal`/bounds/regex constraints

### Added
- `get_attendance_detail(student_alias, detail_url)` — details of one attendance entry
- `get_attendance_frequency(student_alias)` — attendance ratio per semester and overall
- `get_schedule_detail(student_alias, href)` — details of one schedule event
- `get_grades` / `get_attendance` accept `sort_by`: `all` (default), `week`, `last_login`
- `get_homework` accepts an explicit `date_from`/`date_to` range (default unchanged: next 14 days)
- `get_timetable` accepts a `monday` date to fetch any week
- `get_messages` accepts `all_pages=true` — fetches the whole folder (newest first, bounded at 2000 messages, `truncated` flag), including the counter-less sent folder
- Duplicate or blank account aliases are rejected at config load
- CI now enforces the lockfile (`uv lock --check`, `uv sync --locked`) and runs the test suite and a package build

### Changed
- `get_message_content` returns the full message: `{author, title, date, content}` (previously only the content string)
- Expired sessions reported as upstream `TokenError` ("Brak dostępu") now re-authenticate once, like `AuthorizationError`/`TokenKeyError`; Librus maintenance windows and parse failures surface as actionable errors
- Notification state files for aliases needing filename sanitization get a digest suffix, so distinct aliases (e.g. `child/a` vs `child?a`) can never share a state file (plain aliases keep their existing files)
- Direct dependencies (`pydantic`, `beautifulsoup4`, `lxml`, `requests`) are declared explicitly, and all dependency ranges are bounded below the next major version
- `verify_connection.py` rewritten as a credential-gated live smoke test (`--all-accounts` flag)

### Fixed
- `send_message` success reporting: upstream librus-apix returns `success=False` on **every** send (its status check reads `status_code` off a BeautifulSoup object, which is always `None`, and its failure-text check misses the Polish diacritic). Success is now derived from the Librus result text; unrecognized text raises instead of guessing (the exact live strings still await verification with a real send)
- Attachment filenames that sanitize to `..`/`.`/empty now fall back to the ID-based name; the redirect check also pins the port and rejects query strings; the sandbox download honors the client proxy
- `get_completed_lessons` validates the date range (order, 370-day cap) and rejects implausible page counts with a clean error instead of an assert
- GitHub URL typos in `pyproject.toml` and `README.md` (`krzysztoofbury` → `krzysztofbury`)

### Known limitations
- Accounts requiring interactive 2FA are unsupported (no upstream flow)
- Upstream librus-apix v1.5.1 ships a GPL-3.0 `LICENSE` in its repository but MIT metadata on PyPI; an open question to clarify with the upstream maintainer

## [0.4.0] - 2026-06-11

### Added
- `get_final_grades(student_alias)` — end-of-year grade summary per subject: midterm (I), predicted annual (przewidywana roczna, R-in-parentheses column), and annual grade (R). Own scraping: librus-apix parses only current grades and skips these columns entirely. Header-title-driven column mapping handles account-type variants (preschool pages lack the predicted column); a page without the annual column fails loudly instead of returning an empty list

## [0.3.0] - 2026-06-11

### Added
- `get_new_notifications(student_alias)` — everything new since the previous call (grades, attendance, messages, announcements, schedule, homework). Seen-IDs are persisted per student under `state_dir` (default `~/.librus-mcp/state`, override with `LIBRUS_STATE_DIR`)
- `get_recent_schedule_events(student_alias)` — schedule events added since the last Librus login
- `get_message_attachments(student_alias, message_id)` — list attachments of a message (own scraping; librus-apix only exposes a boolean flag)
- `download_attachment(student_alias, message_id, file_id)` — download an attachment via the sandbox.librus.pl GetFile flow to `download_dir` (default `~/.librus-mcp/downloads`, override with `LIBRUS_DOWNLOAD_DIR`)
- `get_behaviour_notes(student_alias)` — behaviour notes (uwagi); own scraping, no Python library covers this
- `get_recipient_groups`, `get_recipients`, `send_message` — messaging tools, disabled by default (write action against the school)
- `features` config section (+ `LIBRUS_FEATURES` env override) to enable/disable optional tools: `notifications`, `attachments`, `behaviour_notes` (default on), `send_message` (default off)

### Changed
- `get_messages` now supports `page` and `folder` ('received'/'sent') and returns `{messages, folder, page, max_page}` instead of `{received}`
- First notifications run diffs against empty IDs instead of `get_initial_notification_data`, which fails with HTTP 403 on `/uczen/index` for parent (rodzic) accounts
- Unknown keys in `features` / `LIBRUS_FEATURES` (and unknown top-level config keys) now raise instead of being silently ignored — a typo must not weaken the send_message gate

### Fixed
- Message paging is 0-based in Librus (verified live: page 0 = newest); previous releases fetched hardcoded page 1, silently returning the older page on mailboxes with more than 50 messages
- Notification state writes use a unique temp filename and a per-alias lock, so concurrent calls can no longer corrupt state or re-report notifications
- Seen-notification IDs are pruned to the newest 500 per category, preventing unbounded state-file growth

## [0.2.0] - 2026-04-13

### Added
- `get_completed_lessons(student_alias, date_from, date_to)` — fetch completed lessons (subject, teacher, topic) for a date range
- `get_student_information(student_alias)` — fetch student profile (name, class, tutor, school, lucky number)
- `get_subject_frequency(student_alias, start?, end?)` — fetch per-subject attendance percentage with optional date range filtering
- `get_homework_detail(student_alias, detail_url)` — fetch full details of a specific homework assignment
- `get_grades` now returns GPA and descriptive grades alongside numeric grades
- Test suite with pytest and pytest-asyncio

### Changed
- Bumped `librus-apix` from `>=0.1.0` to `>=1.5.1` (new auth flow, grades bugfix)
- Bumped `mcp` from `>=0.1.0` to `>=1.25.0` (stdio robustness improvements)

### Removed
- `src/patches.py` — off-by-one grade averaging fix is now upstream in librus-apix 1.5.1

## [0.1.0] - 2026-03-10

### Added
- Initial release
- 9 MCP tools: list_students, get_grades, get_messages, get_message_content, get_attendance, get_homework, get_schedule, get_timetable, get_announcements
- Multi-account support with alias-based configuration
- Automatic token refresh on auth errors
- Three credential sources: env var, config file, secrets.json
- Runtime patch for librus-apix grade averaging bug
