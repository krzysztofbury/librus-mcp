# Changelog

All notable changes to this project will be documented in this file.

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
