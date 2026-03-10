# Librus MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/librus-mcp)](https://pypi.org/project/librus-mcp/)

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that provides AI assistants with access to the **Librus Synergia** electronic gradebook. It supports multiple student accounts simultaneously and exposes tools for grades, messages, attendance, homework, schedules, timetables, and announcements.

## Acknowledgments

This project is built on top of the excellent [**librus-apix**](https://github.com/RustySnek/librus-apix) library by [**RustySnek**](https://github.com/RustySnek). Their work on reverse-engineering and maintaining a Python client for the Librus Synergia platform made this MCP server possible. If you find this project useful, please consider starring their repository as well.

## Quick Start

### 1. Add to your AI assistant

Pick your client. Credentials are passed directly via the `env` block — no files or cloning needed.

#### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "librus": {
      "command": "uvx",
      "args": ["librus-mcp"],
      "env": {
        "LIBRUS_ACCOUNTS": "[{\"alias\":\"daughter\",\"username\":\"12345\",\"password\":\"...\"}]"
      }
    }
  }
}
```

#### Claude Code

Via the `/mcp` command or in `.claude/settings.json`:

```json
{
  "mcpServers": {
    "librus": {
      "command": "uvx",
      "args": ["librus-mcp"],
      "env": {
        "LIBRUS_ACCOUNTS": "[{\"alias\":\"daughter\",\"username\":\"12345\",\"password\":\"...\"}]"
      }
    }
  }
}
```

#### Gemini CLI

Add to `~/.gemini/settings.json` (global) or `.gemini/settings.json` (project-level):

```json
{
  "mcpServers": {
    "librus": {
      "command": "uvx",
      "args": ["librus-mcp"],
      "env": {
        "LIBRUS_ACCOUNTS": "[{\"alias\":\"daughter\",\"username\":\"12345\",\"password\":\"...\"}]"
      }
    }
  }
}
```

#### OpenAI Codex CLI

Add to `~/.codex/config.toml` (global) or `.codex/config.toml` (project-level):

```toml
[mcp_servers.librus]
command = "uvx"
args = ["librus-mcp"]

[mcp_servers.librus.env]
LIBRUS_ACCOUNTS = '[{"alias":"daughter","username":"12345","password":"..."}]'
```

> **Note:** `uvx` automatically downloads and runs the package from PyPI — no cloning or virtual environments needed. You only need [uv](https://github.com/astral-sh/uv) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

### Providing credentials

Each account represents a **parent's login** to Librus Synergia for a specific child. In the Polish school system, parents receive separate Librus login credentials for each of their children. The `alias` is a friendly name you choose to identify which child's data you're accessing. The `username` and `password` are the parent portal credentials you use to log in at [synergia.librus.pl](https://synergia.librus.pl/).

There are three ways to provide credentials (checked in this order):

| Method | Best for | Example |
|--------|----------|---------|
| `LIBRUS_ACCOUNTS` env var | `uvx` users, CI | JSON array of account objects (see examples above) |
| `LIBRUS_CONFIG` env var | Custom file location | Path to your `secrets.json`, e.g. `~/.config/librus/secrets.json` |
| `secrets.json` in working dir | Local development | Create from `secrets.json.template` |

#### Multiple children

Add multiple accounts to the JSON array:

```
[{"alias":"daughter","username":"12345","password":"..."},{"alias":"son","username":"67890","password":"..."}]
```

#### Using a config file with `uvx`

If you prefer a file over inline JSON:

```json
{
  "mcpServers": {
    "librus": {
      "command": "uvx",
      "args": ["librus-mcp"],
      "env": {
        "LIBRUS_CONFIG": "/Users/you/.config/librus/secrets.json"
      }
    }
  }
}
```

### Alternative: Install from source

If you prefer to run from a local clone:

```bash
git clone https://github.com/krzysztoofbury/librus-mcp.git
cd librus-mcp
uv venv && uv pip install -e .
cp secrets.json.template secrets.json   # Then fill in credentials
```

Then use the full path in your MCP config:

```json
{
  "mcpServers": {
    "librus": {
      "command": "/path/to/librus-mcp/.venv/bin/librus-mcp"
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `list_students()` | List configured student aliases |
| `get_grades(student_alias)` | Get grades for a student |
| `get_messages(student_alias)` | Get received messages |
| `get_message_content(student_alias, message_id)` | Get the body of a specific message |
| `get_attendance(student_alias)` | Get attendance records |
| `get_homework(student_alias)` | Get homework for the next 2 weeks |
| `get_schedule(student_alias, year, month)` | Get calendar events/exams for a month |
| `get_timetable(student_alias)` | Get current week's timetable |
| `get_announcements(student_alias)` | Get school announcements |

## Project Structure

```
src/
  server.py          # MCP server with tool definitions and entry point
  librus_client.py   # Librus API client wrapper with caching and retry
  config.py          # Configuration loader (reads secrets.json)
  patches.py         # Runtime patches for librus-apix bugs
```

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Security

To report vulnerabilities, see [SECURITY.md](SECURITY.md).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
