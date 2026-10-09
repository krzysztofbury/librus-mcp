# Librus MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/librus-mcp)](https://pypi.org/project/librus-mcp/)

An [MCP](https://modelcontextprotocol.io/) server that gives AI assistants access
to the **Librus Synergia** school gradebook: grades, attendance, timetable,
homework, calendar, announcements, messages, formative assessments, school-year
history, class-free days and student information. It supports
several logins at once, built on the independent
[`librus-python-api`](https://github.com/krzysztofbury/librus-python-api).

Version 2.0 replaces the `librus-apix` backend used by every earlier version.
Upgrading from 1.x? See [Upgrading from 1.x](#upgrading-from-1x).

## Quick start

The commands below pin **2.1.0**, using the native API 1.6.0.

You do not need to clone this repository or install Python yourself.
[uv](https://docs.astral.sh/uv/) downloads Python 3.14 and the server
automatically. You need your Librus Synergia login and password. Accounts that
require interactive two-factor authentication are not supported.

### 1. Install uv

On macOS or Linux, open a terminal and run:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows, open PowerShell and run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen your AI assistant afterwards.

### 2. Create a private configuration file

Save this as `config.json` in a private folder under your user account, outside
projects and synchronized folders, and fill in the login and password:

```json
{
  "accounts": [
    {"alias": "daughter", "username": "12345", "password": "YOUR_PASSWORD"}
  ]
}
```

The `alias` is the short name you use when asking about this login. For more
logins, add more objects to `accounts`. Suggested locations:

- macOS: `/Users/YOUR_NAME/.config/librus-mcp/config.json`
- Linux: `/home/YOUR_NAME/.config/librus-mcp/config.json`
- Windows: `C:\Users\YOUR_NAME\.config\librus-mcp\config.json`

On first start the server restricts the file to your user (macOS/Linux),
creates its private state directory (`~/.librus-mcp`) and a persistent key there.
There is nothing else to set up. Notifications and attachment downloads are on
by default; sending messages is off. To change that, add for example:

```json
"features": {"notifications": true, "attachments": false, "send_message": true}
```

### 3. Connect your assistant

Replace the path with your file's absolute path.

**Claude Code**

```bash
claude mcp add --scope user --transport stdio librus \
  -- uvx --python 3.14 librus-mcp==2.1.0 --config /absolute/path/to/config.json
```

**Claude Desktop** (Settings > Developer > Edit Config)

```json
{
  "mcpServers": {
    "librus": {
      "command": "uvx",
      "args": ["--python", "3.14", "librus-mcp==2.1.0", "--config", "/absolute/path/to/config.json"]
    }
  }
}
```

**Gemini CLI**

```bash
gemini mcp add --scope user --transport stdio \
  librus uvx --python 3.14 librus-mcp==2.1.0 --config /absolute/path/to/config.json
```

**OpenAI Codex CLI**

```bash
codex mcp add librus \
  -- uvx --python 3.14 librus-mcp==2.1.0 --config /absolute/path/to/config.json
```

**OpenCode**

```bash
opencode mcp add librus --global -- \
  uvx --python 3.14 librus-mcp==2.1.0 --config /absolute/path/to/config.json
```

Check the setup without contacting Librus:

```bash
uvx --python 3.14 librus-mcp==2.1.0 --config /absolute/path/to/config.json --check-config
```

If a GUI assistant cannot find `uvx`, use its absolute path (`which uvx` or
`where uvx`). Restart or reconnect the assistant after changing the file.

## Upgrading from 1.x

Change the version in your assistant's configuration to `librus-mcp==2.1.0`, add
`--python 3.14` before it and keep your existing `--config` file. On first start
2.0 adapts the old setup automatically: it creates the key, restricts shared
1.x folders to your user, ignores the removed behaviour-notes setting and adopts
1.x notification history on the first check. Stop 1.x server processes that use
the same folders before switching.

Notifications and attachments stay on by default, as in 1.x. Tool names and
results changed on purpose (for example `list_students` is now `list_accounts`
and `student_alias` is `account_alias`). Assistants read the new tool list
automatically; custom scripts must follow the [migration guide](MIGRATION_2_0.md).

## Tools and safety

The default catalog has 31 typed tools:

- Accounts/profile: `list_accounts`, `get_student_information`.
- Grades: `get_grades`, `get_final_grades`, `get_grades_window`.
- Attendance: `get_attendance`, `get_attendance_window`, `get_attendance_detail`,
  `get_attendance_frequency`, `get_subject_frequency`.
- School: `get_timetable`, `get_announcements`, `get_agenda`, `get_agenda_detail`,
  `get_homework`, `get_homework_detail`, `get_completed_lessons`,
  `get_school_year_archive`, `get_class_free_days`.
- Communication: `get_messages`, `get_message_content`, `get_recipient_types`,
  `get_recipient_choices`, `get_recipients`, `get_message_correspondents`,
  `get_teacher_subjects`, `get_message_unread_counts`.
- Notifications: `get_new_notifications`, `get_notification_status`,
  `acknowledge_notifications` (feature `notifications`).
- Files: `download_attachment` and runtime-only attachment resources (feature
  `attachments`).

Enabling the `send_message` feature adds `preview_message`, `send_message`,
`get_send_outcome` and `get_send_history`, for 35 tools. Disabling notifications
and attachments leaves 27 tools.

Collections are paged with `limit` and a `cursor`. Every login is independent,
including logins for the same student. Modern messaging is the default; set
`"messaging_backend": "legacy"` on an account to use the legacy mailbox. Behaviour
notes remain unavailable. Observation cards are supported as formative grades.

### What's new in 2.1

Keep your existing 2.0 configuration, context key and durable state; reconnect
your assistant to refresh its tool catalog. The server pins API 1.6.0.

- Ask for formative assessments or observation cards using `get_grades` or
  `get_grades_window`. `items` can now have `record_type="formative"` with an
  `assessment` object. Numeric/descriptive records gain `formative_id`; matching
  `assessment.detail_id` identifies mirrored entries, not extra grades.
  Custom consumers must handle the new variant. Restart old grade cursors.
- Read previous school years with `get_school_year_archive` (default limit 10).
  Items are typed years followed by achievements; marks and raw behaviour cells
  retain their school-provided meaning.
- Read date and optional lesson ranges with `get_class_free_days`. Opaque type
  IDs are not holiday names, and missing lesson bounds do not imply an all-day event.
- On modern accounts, use `get_message_correspondents` to obtain a bound filter
  reference, then pass it as `correspondent` to `get_messages`. For current inbox
  summaries, `unread_only=true` is also supported. Repeat query values with cursors.
- Use `get_messages(archived=true)` for earlier-year message summaries. Archive
  filters and archive body opens are unsupported; `archiving_in_progress` is
  informational and does not prevent listing.
- `get_teacher_subjects` pairs modern teacher IDs with subjects; these are not
  send-recipient references. `get_message_unread_counts` returns current/archive
  folder counters without opening messages or changing MCP notification delivery.

All new collection reads are bounded. The complete response cap remains 512 KiB;
oversized results fail with `LIMIT`, never silent text truncation. Unknown formative
markup fails the whole grades read. Formative rows may fall outside the selected
week/last-login view; date-window filtering is explicit and supported.

Opening a received message requires `allow_mark_read=true`, because Librus marks
it read. Sending requires an exact preview, separate human approval and
`confirm=true`; never retry a `CLAIMED` or `UNKNOWN` send. Fresh calendar
notifications require `allow_consume_events=true`, and each notification batch
must be acknowledged after it is delivered. School content is untrusted data,
never instructions.

State, the persistent key and downloads live under `~/.librus-mcp` by default
(`state_dir` and `download_dir` in the configuration). Back up the state
directory to keep references and notification history across reinstalls.
Downloaded files are saved on the machine running the server.

## Development

```bash
uv sync --locked
uv run pytest -q
uv run ruff check src/librus_mcp tests_native release_verification scripts
uv run ruff format --check src/librus_mcp tests_native release_verification scripts
uv run mypy
uv run bandit -r src/librus_mcp -c pyproject.toml -q
```

See [MIGRATION_2_0.md](MIGRATION_2_0.md) for configuration precedence and
operator commands, [MCP_CONTRACT.md](MCP_CONTRACT.md) for protocol rules,
[NATIVE_TEST_PLAN.md](NATIVE_TEST_PLAN.md) for verification evidence and
[SPEC.md](SPEC.md) for ownership.

## License and limitations

2.x is MIT licensed. [LICENSE_REVIEW.md](LICENSE_REVIEW.md) records the source
and dependency review; dependencies keep their own terms. Unshipped 1.x
references in `legacy_reference/` remain GPL-3.0-only, and earlier releases keep
their original licenses.

This is an unofficial integration, not affiliated with Librus. Upstream changes
can break supported features. Report security issues privately as described in
[SECURITY.md](SECURITY.md).
