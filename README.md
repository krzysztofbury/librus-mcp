# Librus MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that provides AI assistants with access to the **Librus Synergia** electronic gradebook. It supports multiple student accounts simultaneously and exposes tools for grades, messages, attendance, homework, schedules, timetables, and announcements.

## Acknowledgments

This project is built on top of the excellent [**librus-apix**](https://github.com/RustySnek/librus-apix) library by [**RustySnek**](https://github.com/RustySnek). Their work on reverse-engineering and maintaining a Python client for the Librus Synergia platform made this MCP server possible. If you find this project useful, please consider starring their repository as well.

## Prerequisites

- Python 3.10+
- A valid [Librus Synergia](https://synergia.librus.pl/) account

## Installation

1. **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/librus-mcp.git
    cd librus-mcp
    ```

2. **Create a virtual environment and install dependencies:**

    Using [uv](https://github.com/astral-sh/uv) (recommended):
    ```bash
    uv venv
    uv pip install -e .
    ```

    Or using pip:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e .
    ```

3. **Configure your accounts:**
    ```bash
    cp secrets.json.template secrets.json
    ```
    Edit `secrets.json` with your Librus credentials. Each account represents a **parent's login** to Librus Synergia for a specific child. In the Polish school system, parents receive separate Librus login credentials for each of their children. The `alias` is a friendly name you choose to identify which child's data you're accessing:
    ```json
    {
      "accounts": [
        { "alias": "daughter", "username": "12345", "password": "..." },
        { "alias": "son", "username": "67890", "password": "..." }
      ]
    }
    ```
    The `username` and `password` are the parent portal credentials you use to log in at [synergia.librus.pl](https://synergia.librus.pl/).

4. **Verify the connection (optional):**
    ```bash
    python verify_connection.py
    ```

## Usage

### Running the Server

```bash
python src/server.py
```

### Adding to Claude Desktop

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "librus": {
      "command": "/path/to/librus-mcp/.venv/bin/python",
      "args": ["/path/to/librus-mcp/src/server.py"]
    }
  }
}
```

### Adding to Claude Code

Add the following to your Claude Code MCP settings (`.claude/settings.json` or via the `/mcp` command):

```json
{
  "mcpServers": {
    "librus": {
      "command": "/path/to/librus-mcp/.venv/bin/python",
      "args": ["/path/to/librus-mcp/src/server.py"]
    }
  }
}
```

### Adding to Gemini CLI

Add the following to `~/.gemini/settings.json` (global) or `.gemini/settings.json` (project-level):

```json
{
  "mcpServers": {
    "librus": {
      "command": "/path/to/librus-mcp/.venv/bin/python",
      "args": ["/path/to/librus-mcp/src/server.py"]
    }
  }
}
```

### Adding to OpenAI Codex CLI

Add the following to `~/.codex/config.toml` (global) or `.codex/config.toml` (project-level):

```toml
[mcp_servers.librus]
command = "/path/to/librus-mcp/.venv/bin/python"
args = ["/path/to/librus-mcp/src/server.py"]
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
  server.py          # MCP server with tool definitions
  librus_client.py   # Librus API client wrapper with caching and retry
  config.py          # Configuration loader (reads secrets.json)
  patches.py         # Runtime patches for librus-apix bugs
```

## Contributing

Contributions are welcome!

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
