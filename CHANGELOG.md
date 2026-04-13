# Changelog

All notable changes to this project will be documented in this file.

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
