# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Added

- Verify the installed wheel, local diagnostics, and MCP stdio initialization on
  Linux, macOS, and Windows in every pull request.
- Publish an evidence-based operating-system and MCP-client compatibility matrix,
  including tested client versions and explicit coverage limits.
- Document OpenCode setup alongside the existing MCP client instructions.

## [1.3.0] - 2026-09-18

### Added

- Add `--version`, `--check-config`, `doctor`, and explicit `doctor --live`
  commands with credential-safe, actionable output for end users.
- Add a first-class `--config PATH` option shared by MCP startup and diagnostics.
- Check notification storage, attachment storage, hard-link support, and optional
  read-only Librus access without exposing credentials or raw upstream errors.

### Documentation

- Use one version-pinned, explicit configuration path across supported clients;
  document deliberate upgrades, track-latest installs, GUI PATH recovery,
  reconnect requirements, and the local-only stdio and attachment-path model.

## [1.2.6] - 2026-09-17

### Fixed

- Automatically restrict an existing POSIX notification-state directory to
  mode `0700` when ownership and the path can be repaired safely. Default-path
  upgrades no longer require users to repair permissions manually, while
  symlinked, foreign-owned, and unsafe shared-parent paths remain rejected.

## [1.2.5] - 2026-09-17

### Security

- Replace assertions over upstream HTML and gateway JSON with explicit parse
  errors that remain active under optimized Python.
- Require every parsed behaviour note to contain a non-empty date and content;
  incomplete pages fail instead of returning partial or misleading records.
- Make behaviour notes experimental and default-off until a populated live page
  can be anonymized and added as an integration fixture.
- Cooperatively stop attachment workers after caller cancellation or timeout and
  serialize cancellation against atomic publication, preventing a worker from
  publishing a file after cancellation wins the commit boundary.

### Fixed

- Normalize malformed subject-frequency attendance envelopes and nested records
  to parse errors.
- Abort attachment response streams on cancellation, enforce the absolute
  deadline against slow-drip bodies, reject encoded response bodies that could
  buffer outside the download loop, and remove temporary files when cancellation
  is observed during or after streaming.

## [1.2.4] - 2026-09-17

### Security

- Limit ordinary Librus and gateway response bodies to 4 MiB while streaming,
  including responses without a trusted `Content-Length`. Attachment downloads
  retain their separate 50 MiB streaming limit.
- Process at most 500 recent schedule events per call. Each complete read-once
  result is checkpointed as one bounded atomic spool batch before the limit is enforced, so an
  oversized consumed result can drain safely across later calls instead of being
  discarded when one in-memory batch is too large.
- Bound message pages to 50 items, all-pages results to 2,000 items, completed
  lessons to 100 pages and 10,000 items, attendance to 10,000 records, and
  subject-frequency fan-out to 2,000 lessons and 500 subjects.
- Constrain `send_message` titles, content, recipient count, recipient ID length,
  and total UTF-8 payload size. Recipient IDs must be unique ASCII digit strings
  in both the MCP schema and runtime validation.

### Fixed

- Reject reversed `get_subject_frequency` date ranges before making a request.
- Treat the completed-lessons limit as 100 pages rather than accepting a
  zero-based last-page index of 100 and fetching 101 pages.
- Add `truncated` to single-page message results and truncate malformed upstream
  pages that contain more than the expected 50 messages.

### Release

- Refuse publication when the release tag, event commit, checked-out tag, and
  `project.version` disagree.
- Run lockfile, lint, format, security, test, build, and clean installed-wheel MCP
  handshake checks before trusted publication to PyPI.
- Pin every third-party GitHub Action to an immutable commit SHA.

## [1.2.3] - 2026-09-16

### Security

- Store account passwords as Pydantic `SecretStr` values and unwrap them only at
  the Librus authentication boundary. Configuration validation and startup errors
  omit input values, so malformed account entries cannot print sibling credentials.
- Reject POSIX credential files accessible by group or other users with an
  actionable `chmod 600` error. Invalid startup configuration now produces one
  redacted stderr diagnostic and exits without a traceback.
- Create notification state directories with mode `0700` and atomically published
  state, legacy-mirror, pending-event, and lock files with mode `0600` on POSIX.
- Require regular notification state files and bound reads to 4 MiB before JSON
  parsing. Pending schedule events are additionally bounded to 64 KiB each and
  128 KiB per save/load batch. Validate the exact schema, category size,
  notification ID type, and ID length before constructing upstream state objects
  or persisting new state.
- Reject account aliases with surrounding whitespace, control characters, or more
  than 80 characters. Unknown account fields are now configuration errors instead
  of being silently ignored.
- Centralize every `LIBRUS_*` environment variable, default, path expansion, and
  source-priority rule in `src/config.py` using Pydantic Settings. Feature modules
  now consume one validated `AppConfig` instead of reading the environment.

### Testing

- Add credential-redaction, startup-error, authentication-boundary, POSIX mode,
  oversized-state, malformed-ID, and alias-boundary coverage.

## [1.2.2] - 2026-09-15

### Security

- Treat a second authentication-class failure after a successful fresh login as
  persistent endpoint denial, evict the fresh client, and apply a 60-second
  cooldown scoped to that student alias and operation. Repeated calls now fail
  fast without creating unbounded login pressure, while unrelated tools and
  aliases remain available. Three distinct persistently denied operations in
  one window trigger an alias-wide cooldown to bound cross-operation cycling.
- Evict a cached client after an authentication-class failure from a
  non-idempotent operation without retrying the operation.

### Testing

- Add focused, repeatable Cosmic Ray campaigns for authentication and local-state
  safety logic, including explicit line and operator filtering.
- Add mutation-driven coverage for authorization cooldown boundaries, persistent
  denial across all supported authentication exceptions, state schema checks,
  collection-size bounds, recursive state-directory creation, content-addressed
  spool integrity, and stable Unicode event identities.

### License

- Relicense the project from MIT to GPL-3.0-only. The required
  `librus-apix==1.5.1` dependency declares MIT in its package metadata, but its
  repository and the license files shipped inside both PyPI distributions contain
  GPL-3.0. This project now follows the strongest terms actually conveyed with the
  dependency instead of relying on contradictory metadata.

## [1.2.1] - 2026-09-15

### Fixed

- Checkpoint read-once schedule events to independent,
  content-addressed local spool files before notification processing continues.
  After a successful local checkpoint, cancellation or a later seen-state write
  failure preserves those events for the next call instead of silently losing them.
- Run the standalone `get_recent_schedule_events` tool through the same
  in-process and cross-process state transaction as aggregate notifications.
- Replace schedule-event identities based only on MD5 of event text with
  canonical SHA-256 identities covering the added date, event type, and text.
  Existing MD5-only state migrates conservatively with a one-time replay rather
  than risking the loss of a later event that reuses the same text.

### Changed

- Mark `get_recent_schedule_events` as state-mutating and non-idempotent because
  Librus consumes this upstream view when it is read.
- Document interrupted schedule recovery as at-least-once delivery: a recovered
  event may be replayed rather than lost.
- Rewrite Quick Start for non-technical users around a private credentials file,
  copyable client commands, connection verification, and common setup failures.
- Add Cosmic Ray to the development dependencies for the next security work group.

## [1.2.0] - 2026-09-09

### Added
- Typed MCP output schemas for `get_recipient_groups` and `get_recipients`, so
  clients can validate recipient discovery results before constructing a send
  request

### Changed
- Adopt the focused, useful subset of ruff 0.16's expanded default checks:
  import ordering, modern type syntax, class-variable annotations, nested
  context-manager simplification, accurate exception types, timezone-aware
  date defaults, and removal of a blind configuration exception handler
- Interpret default homework, timetable, and notification ranges in the
  `Europe/Warsaw` school timezone. Date-only Librus inputs are represented as
  civil dates rather than naive datetimes

## [1.1.0] - 2026-09-01

### Changed
- **Requires the 2.x line of the MCP Python SDK** (`mcp>=2.1.1,<3`, up from
  `mcp>=1.25.0,<2`). The 1.x entry point this server was built on, `FastMCP`
  from `mcp.server.fastmcp`, was renamed to `MCPServer` in
  `mcp.server.mcpserver`, so the two SDK majors are not interchangeable: on
  mcp 2.x the previous release fails at import, and this release fails at
  import on mcp 1.x.

  **This is not a change to the tool surface.** All 22 tools, their argument
  schemas, their `ToolAnnotations`, and the protocol handshake are unchanged,
  so MCP hosts need no configuration change and `uvx librus-mcp` users need
  take no action. Only a caller that pins the SDK itself in a shared
  environment is affected.

  Verified on mcp 2.1.1: the `@mcp.tool()` decorator and its `annotations`
  argument are unchanged, and `run()` still defaults to the stdio transport.
  `ToolAnnotations` field names moved to snake_case upstream, so the tool
  annotation constants and the tests that assert on them now use the canonical
  snake_case spellings; the values still serialize to camelCase on the wire, as
  the protocol requires, which was confirmed by reading a real `tools/list`
  response over stdio rather than inferred.

- Refresh the lockfile and move the supply-chain quarantine cutoff from
  2026-06-14 to 2026-09-01. The locked set now matches what a current `uvx`
  launch resolves, so CI stops validating versions that no deployment runs
- Pin the ruff rule selection explicitly. ruff 0.16 widened its implicit
  default rule set, which turned a dev-dependency upgrade into 71 lint errors
  in unchanged code. `[tool.ruff.lint] select` now states the selection that
  was in effect through 0.15.x, so the enforced rules no longer depend on the
  installed tool version

### Fixed
- The `initialize` handshake advertised the MCP SDK's own version as this
  server's version, so hosts displayed the SDK version (for example 1.29.1)
  instead of the librus-mcp version. The server now passes its own version,
  read from installed package metadata, so there is a single source of truth
  and no value to keep in sync by hand

### Security
- Raise dependency floors to the first patched release for each published
  advisory affecting the previously locked versions: `lxml` 6.1.0 (XXE through
  the default `iterparse()` and `ETCompatXMLParser()` configuration),
  `requests` 2.33.0 (insecure temporary file reuse in
  `extract_zipped_paths()`), and `aiohttp` 3.14.2 (multipart CRLF injection,
  unbounded request pipelining, unbounded trailer headers, request smuggling
  on WebSocket upgrade). The move to mcp 2.x likewise clears three advisories
  that affected the previously locked 1.25.0 (unverified authenticated
  principal on HTTP transports, cross-client task access, missing WebSocket
  Host/Origin validation).

  None of these are reachable from this server: it runs the stdio transport
  only, and it uses `aiohttp` purely as a client with an in-memory cookie jar
  that is never persisted. The floors matter because the entry point is
  normally launched with `uvx`, which resolves from PyPI at launch, so an
  installed copy could otherwise be served an affected version.

### Added
- Scheduled `Dependency drift` workflow that resolves the newest permitted
  dependency versions past the project cutoff and runs the suite against them,
  so an upstream break surfaces in CI rather than at a user's launch

## [1.0.0] - 2026-08-21

### Changed
- **BREAKING**: require Python 3.14 or newer and test the package on Python
  3.14 in CI. Python 3.10 through 3.13 are no longer supported
- Keep per-account HTTP connection pools alive across Librus requests, stream
  attachments to atomically published temporary files, and avoid duplicate
  HTML parsing
- Deduplicate and bound gateway requests for per-subject attendance, fetch
  notification categories through isolated clients with at most three workers,
  and reuse the first response when paginating messages and completed lessons

### Fixed
- Apply login cooldowns only after authentication failures or confirmed login
  throttling, so transient network failures can be retried immediately
- Use full SHA-256 digests for sanitized notification-state filenames and
  migrate existing short-digest files without losing seen-notification history

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
