# Librus MCP Server

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/librus-mcp)](https://pypi.org/project/librus-mcp/)

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that provides AI assistants with access to the **Librus Synergia** electronic gradebook. It supports multiple student accounts simultaneously and exposes tools for grades (numeric, GPA, and descriptive), messages, attendance, homework, schedules, timetables, announcements, completed lessons, and student information.

## Quick Start

You do not need to clone this repository or install Python yourself. The setup
uses [uv](https://github.com/astral-sh/uv), which installs the correct Python
version and Librus MCP automatically.

You need your parent login and password for
[Librus Synergia](https://synergia.librus.pl/). Accounts requiring interactive
two-factor authentication are not supported by the underlying library.

### 1. Install uv

On macOS or Linux, open a terminal and run:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows, open PowerShell and run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen your AI assistant after installing uv. You can verify the
installation in a new terminal with `uvx --version`.

### 2. Create a private credentials file

Create a file named `secrets.json` in a private folder under your user account,
outside projects and shared or synchronized folders:

```json
{
  "accounts": [
    {
      "alias": "daughter",
      "username": "12345",
      "password": ""
    }
  ]
}
```

Replace the empty `password` value with your Librus password. The `alias` is the
short name you will use when asking your assistant about this student. For more
than one child, add another account object to the array.

Use the absolute path to this file in the next step. Example paths:

- macOS: `/Users/YOUR_NAME/.config/librus-mcp/secrets.json`
- Linux: `/home/YOUR_NAME/.config/librus-mcp/secrets.json`
- Windows JSON: `C:\\Users\\YOUR_NAME\\AppData\\Roaming\\librus-mcp\\secrets.json`

On macOS or Linux, protect the finished file so only your user can read it:

```bash
chmod 600 /absolute/path/to/secrets.json
```

### 3. Connect your AI assistant

Choose only the client you use. Replace `/absolute/path/to/secrets.json` with
the path created above.

#### Claude Desktop

Open **Settings > Developer > Edit Config** and add this MCP server. The config
file is normally at `~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS or `%APPDATA%\Claude\claude_desktop_config.json` on Windows.

```json
{
  "mcpServers": {
    "librus": {
      "command": "uvx",
      "args": ["librus-mcp==1.3.0", "--config", "/absolute/path/to/secrets.json"]
    }
  }
}
```

#### Claude Code

Run this once in a terminal:

```bash
claude mcp add --scope user --transport stdio librus \
  -- uvx librus-mcp==1.3.0 --config /absolute/path/to/secrets.json
```

#### Gemini CLI

Run this once in a terminal. User scope keeps school credentials out of project files.

```bash
gemini mcp add --scope user --transport stdio \
  librus uvx librus-mcp==1.3.0 --config /absolute/path/to/secrets.json
```

#### OpenAI Codex CLI

Run this once in a terminal:

```bash
codex mcp add librus \
  -- uvx librus-mcp==1.3.0 --config /absolute/path/to/secrets.json
```

#### OpenCode

Add this server to `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "librus": {
      "type": "local",
      "command": [
        "uvx",
        "librus-mcp==1.3.0",
        "--config",
        "/absolute/path/to/secrets.json"
      ],
      "enabled": true
    }
  }
}
```

Never put a Librus password or `LIBRUS_ACCOUNTS` in a project-level MCP
configuration. Project files can be committed, synchronized, or shared.

### 4. Restart and verify

1. Completely restart Claude Desktop, or reconnect Librus in your CLI client.
2. Ask: **"Use Librus to list the configured students."**
3. Check that your chosen aliases appear.
4. Ask: **"Use Librus to show grades for daughter."** Replace `daughter` with
   your alias. This second request performs a real Librus login.

For CLI status checks, use `claude mcp list`, `gemini mcp list`, or
`codex mcp list`. Claude Code and Gemini CLI also expose status through `/mcp`.

Repeat the restart or reconnect step after changing credentials, enabled
features, storage folders, or the Librus MCP version. A running MCP process does
not reload configuration changes.

### 5. Diagnose problems

These commands are safe to run in a terminal. Replace the example path with the
same credentials path used in your MCP configuration.

```bash
uvx librus-mcp==1.3.0 --version
uvx librus-mcp==1.3.0 --config /absolute/path/to/secrets.json --check-config
uvx librus-mcp==1.3.0 --config /absolute/path/to/secrets.json doctor
```

`--check-config` validates the file without signing in. `doctor` also prepares
and checks local notification and attachment storage without contacting Librus.
Neither command prints usernames or passwords.

For an explicit sign-in and read-only check of every configured account, run:

```bash
uvx librus-mcp==1.3.0 --config /absolute/path/to/secrets.json doctor --live
```

Live doctor mode reads only the student profile. It does not change grades,
messages, attendance, or other school data.

### Upgrading

The recommended configuration pins an exact version so an update cannot change
behavior without your decision. To upgrade, replace the old version number in
your MCP configuration, completely restart or reconnect the client, and run the
version and doctor commands above.

To track new releases automatically instead, remove `==1.3.0` and use
`librus-mcp` as the `uvx` package argument. This is less predictable because a
future release may be selected after a restart.

### Troubleshooting

- **`uvx` not found:** run `uvx --version` in a new terminal, then completely
  restart the AI assistant. GUI applications may require the absolute path to
  `uvx`. On macOS or Linux, get it with `command -v uvx`. In PowerShell, run
  `(Get-Command uvx).Source`. Put the returned path in the MCP `command` field.
- **Config file does not exist:** copy the exact file path and prefer an absolute
  path. In JSON on Windows, write each backslash twice, for example
  `C:\\Users\\...`.
- **Credential file permissions are too open:** on macOS or Linux, run
  `chmod 600 /absolute/path/to/secrets.json`. The server refuses files readable
  or writable by group or other users.
- **Aliases appear but grades fail:** verify the same parent credentials at
  [synergia.librus.pl](https://synergia.librus.pl/).
- **Login requires a second factor:** interactive 2FA accounts are not currently supported.

## Compatibility

Every pull request builds and installs the wheel on GitHub-hosted runners, then
checks `--version`, configuration validation, local doctor storage operations,
and an MCP `initialize` exchange over stdio. These checks use synthetic
credentials and do not contact Librus, so they do not cover live authentication
or upstream network behavior.

| Operating system | Automated check | Status |
|------------------|-----------------|--------|
| Linux (`ubuntu-latest`) | Every pull request | Installed-wheel smoke-tested |
| macOS (`macos-latest`) | Every pull request | Installed-wheel smoke-tested |
| Windows (`windows-latest`) | Every pull request | Installed-wheel smoke-tested |

Client setup was checked on 2026-09-18. Client and operating-system dimensions
are tested separately; the table does not claim that every client and OS pair
has been exercised end to end.

| MCP client | Checked version | Check performed | Status |
|------------|-----------------|-----------------|--------|
| Claude Desktop | Current config format | JSON setup reviewed | Runtime check pending |
| Claude Code | 2.1.270 on Linux | `mcp add` and `mcp get` accepted the documented command | Setup verified |
| Gemini CLI | 0.59.0 on Linux | `mcp add` and `mcp list` accepted the documented command | Setup verified |
| OpenAI Codex CLI | 0.154.0 on Linux | `mcp add` and `mcp get` accepted the documented command | Setup verified |
| OpenCode | 1.18.30 on Linux | Local stdio configuration connected | Connection verified |

All clients use the same local stdio server and require a restart or reconnect
after configuration changes. A setup-verified entry confirms that the client
accepted the documented configuration; the cross-platform MCP handshake above
provides the automated server protocol check.

## Configuration Reference

Credential sources are checked in this order and are not merged:

1. The explicit `--config PATH` option, if supplied.
2. `LIBRUS_ACCOUNTS`, if set.
3. The file path in `LIBRUS_CONFIG`, if set.
4. `secrets.json` in the server working directory.
5. `secrets.json` beside a source checkout.

Invalid higher-priority configuration produces an error instead of silently
falling back. `LIBRUS_FEATURES`, `LIBRUS_STATE_DIR`, and `LIBRUS_DOWNLOAD_DIR`
provide separate overrides for optional tools and local storage.

The `--config PATH` command-line option has priority over `LIBRUS_ACCOUNTS` and
`LIBRUS_CONFIG`. It is the recommended path for normal desktop and CLI setup.

All `LIBRUS_*` environment variables, JSON-file values, defaults, and source
priorities are declared and resolved in `src/config.py` with Pydantic Settings.
The rest of the application receives one validated `AppConfig` snapshot and
does not read configuration directly from the environment.

Account aliases must be 1 to 80 printable characters with no surrounding
whitespace. Unknown account fields are rejected. Passwords are redacted from
validation and startup errors.

Librus MCP is a local stdio program. It does not open a network port or expose a
web service. It runs on the same computer as the AI assistant, and attachment
paths returned by tools refer to files on that computer.

For advanced environments, `LIBRUS_ACCOUNTS` accepts a JSON array directly:

```text
[{"alias":"daughter","username":"12345","password":"..."}]
```

## Alternative: Install from Source

If you prefer to run from a local clone:

```bash
git clone https://github.com/krzysztofbury/librus-mcp.git
cd librus-mcp
uv venv && uv pip install -e .
```

Point `LIBRUS_CONFIG` at the private credentials file created during Quick Start,
then use the local executable in your MCP config:

```json
{
  "mcpServers": {
    "librus": {
      "command": "/path/to/librus-mcp/.venv/bin/librus-mcp",
      "env": {
        "LIBRUS_CONFIG": "/absolute/path/to/secrets.json"
      }
    }
  }
}
```

Contributors can run the credentialed source-tree smoke test with
`uv run python verify_connection.py --all-accounts`.

## Available Tools

| Tool | Description |
|------|-------------|
| `list_students()` | List configured student aliases |
| `get_grades(student_alias, sort_by?)` | Get numeric grades, GPA, and descriptive grades (`all`, `week`, or `last_login`) |
| `get_final_grades(student_alias)` | Get end-of-year summary per subject: midterm, predicted annual (przewidywana roczna), and annual grade |
| `get_messages(student_alias, page?, folder?, all_pages?)` | Get one page of messages from the `received` or `sent` folder, or the whole folder (50 messages per page, 2000 overall, with truncation metadata) |
| `get_message_content(student_alias, message_id)` | Get a message: author, title, date, and content |
| `get_attendance(student_alias, sort_by?)` | Get attendance records (`all`, `week`, or `last_login`) |
| `get_attendance_detail(student_alias, detail_url)` | Get details of one attendance entry by its numeric Librus ID |
| `get_attendance_frequency(student_alias)` | Get attendance frequency per semester and overall |
| `get_subject_frequency(student_alias, start?, end?)` | Get per-subject attendance percentage, optionally filtered by date range |
| `get_homework(student_alias, date_from?, date_to?)` | Get homework for a date range (default: next 2 weeks) |
| `get_homework_detail(student_alias, detail_url)` | Get full details of a homework assignment by its numeric Librus ID |
| `get_schedule(student_alias, year, month)` | Get calendar events/exams for a month |
| `get_schedule_detail(student_alias, href)` | Get details of one schedule event (test scope, room, teacher) |
| `get_recent_schedule_events(student_alias)` | Get schedule events added since the last Librus login. This consumes a read-once Librus view and safely checkpoints its events locally |
| `get_timetable(student_alias, monday?)` | Get a week's timetable (default: current week; `monday` picks another week) |
| `get_announcements(student_alias)` | Get school announcements |
| `get_completed_lessons(student_alias, date_from, date_to)` | Get completed lessons (subject, teacher, topic) for a date range |
| `get_student_information(student_alias)` | Get student profile (name, class, tutor, school, lucky number) |

All tools carry MCP `ToolAnnotations` (read-only / destructive / idempotent
hints), so MCP hosts can apply their own safety policies.

### Optional tools (feature gates)

These tools are registered based on the `features` section of the configuration
(or the `LIBRUS_FEATURES` env var, a JSON object merged over it):

| Tool | Feature gate | Default | Description |
|------|--------------|---------|-------------|
| `get_new_notifications(student_alias)` | `notifications` | on | Everything new since the previous call (grades, attendance, messages, announcements, schedule, homework). Seen-state is persisted per student |
| `get_message_attachments(student_alias, message_id)` | `attachments` | on | List attachments (filename + file ID) of a message |
| `download_attachment(student_alias, message_id, file_id)` | `attachments` | on | Download an attachment to the download directory |
| `get_behaviour_notes(student_alias)` | `behaviour_notes` | **off** | Experimental behaviour notes (uwagi): date, teacher, category, content |
| `get_recipient_groups(student_alias)` | `send_message` | **off** | List recipient groups for messaging |
| `get_recipients(student_alias, group)` | `send_message` | **off** | List recipients (name → ID) in a group |
| `send_message(student_alias, title, content, recipient_ids, confirm_token?)` | `send_message` | **off** | Send a real message to school staff — enable deliberately |

`send_message` uses a two-step confirmation: the first call sends nothing and
returns a preview plus a single-use `confirm_token` (valid 5 minutes); only a
second call with that token delivers the message. Titles are limited to 200
characters, content to 15,000 characters, and a call to 50 unique numeric
recipient IDs. The combined UTF-8 payload is limited to 64 KiB.

Librus exposes recently added schedule events only once. Librus MCP checkpoints
each complete result locally as one atomic batch before continuing. After that
checkpoint succeeds, a cancelled call or failed state update can replay the event
instead of losing it. Recovery uses at-least-once delivery, so a replayed schedule
event may appear again. A connection failure, parse failure, local storage failure,
or machine crash before the atomic checkpoint completes can still lose data from
this read-once upstream view. Calls process at most 500 schedule events; a larger
consumed result remains in the bounded spool and drains across later calls before
another read-once schedule request is made.

Non-attachment Librus responses are streamed with a 4 MiB body limit, including
chunked responses and the cumulative bodies in a redirect chain. Attachment
downloads use their separate 50 MiB streaming cap.

Attachment downloads cooperate with caller cancellation and operation timeouts.
Cancellation actively closes a blocked response stream and is serialized against
the final atomic publication step, so a download cannot publish later after
cancellation wins that commit boundary. Available bytes are processed without
waiting for a 64 KiB buffer to fill, so the absolute download deadline also
applies to slow-drip responses. Requests require identity content encoding and
reject encoded bodies that could buffer outside this bounded download loop.

Behaviour notes default off because only the empty page has been verified against
live Synergia markup. Operators may opt in with `behaviour_notes: true`; malformed
or incomplete note layouts fail explicitly instead of returning partial records.

Example with all options:

```json
{
  "accounts": [{"alias": "daughter", "username": "12345", "password": "..."}],
  "features": {
    "notifications": true,
    "attachments": true,
    "behaviour_notes": true,
    "send_message": false
  },
  "state_dir": "~/.librus-mcp/state",
  "download_dir": "~/.librus-mcp/downloads"
}
```

| Setting | Env override | Default | Purpose |
|---------|--------------|---------|---------|
| `features` | `LIBRUS_FEATURES` | see above | Enable/disable optional tools |
| `state_dir` | `LIBRUS_STATE_DIR` | `~/.librus-mcp/state` | Per-student seen-notification state |
| `download_dir` | `LIBRUS_DOWNLOAD_DIR` | `~/.librus-mcp/downloads` | Attachment download target |

Attachment files are streamed to an exclusive temporary file and published
atomically without overwriting existing files. The download directory must be
on a filesystem that supports hard links.

## Project Structure

```
src/
  cli.py                 # End-user startup, configuration checks, and doctor
  server.py              # MCP server with tool definitions and entry point
  librus_client.py       # Librus API client wrapper with caching and retry
  config.py               # All operator settings, defaults, and source precedence
  notification_state.py   # Seen IDs and read-once schedule recovery spool
  scraping.py            # Own Synergia scraping: attachments, behaviour notes
tests/                   # pytest suite with mocked librus-apix
```

## Acknowledgments

This project is built on the excellent
[librus-apix](https://github.com/RustySnek/librus-apix) library by
[RustySnek](https://github.com/RustySnek). Its reverse-engineered Librus client
makes this MCP server possible.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Security

To report vulnerabilities, see [SECURITY.md](SECURITY.md).

## License

Copyright (C) 2026 Krzysztof Bury.

This project is licensed under the GNU General Public License v3.0 only
(`GPL-3.0-only`). See [LICENSE](LICENSE) for the complete terms.

The project adopted GPL-3.0-only in v1.2.2 to honor the strongest license terms
actually distributed with its required `librus-apix==1.5.1` dependency. That
dependency declares MIT in package metadata, but both its source repository and
the `LICENSE` files bundled in its PyPI wheel and source archive contain the
complete GPL-3.0 text. Using GPL-3.0-only avoids relying on the contradictory
metadata when redistributing this combined application.
