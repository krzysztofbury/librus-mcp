# SPEC.md - Agent/Bot Specification for librus-mcp

This document describes how AI agents and bots should interact with this codebase.

## Project Overview

**librus-mcp** is an MCP (Model Context Protocol) server that wraps the [librus-apix](https://github.com/RustySnek/librus-apix) library to expose Librus Synergia gradebook data as tools for AI assistants.

- **Language:** Python 3.10+
- **Package manager:** [uv](https://github.com/astral-sh/uv) (preferred) or pip
- **Formatter/Linter:** [ruff](https://github.com/astral-sh/ruff) (line-length: 100, target: py310)
- **Build system:** hatchling
- **License:** MIT

## Architecture

```
src/
  server.py          - FastMCP server. Defines all MCP tools. Entry point.
  librus_client.py   - LibrusManager class. Handles auth, caching, retry, and data fetching.
  config.py          - Reads secrets.json via Pydantic models.
  patches.py         - Monkey-patches for librus-apix bugs. Applied at startup.
```

### Key Design Decisions

1. **All librus-apix calls are blocking** and run via `asyncio.to_thread()`.
2. **Client instances are cached** per student alias in `LibrusManager._instances`.
3. **Token expiry is handled** by `_execute()` which retries once on auth-related errors.
4. **Config is loaded once** and cached in `LibrusManager._config_cache`.
5. **Dataclasses are converted** to dicts via `to_dict()` for JSON-RPC serialization.

## How to Work With This Codebase

### Setup

```bash
uv venv && uv pip install -e .
cp secrets.json.template secrets.json  # Then fill in credentials
```

### Running

```bash
python src/server.py          # Start the MCP server
python verify_connection.py   # Test connectivity
```

### Linting and Formatting

```bash
uvx ruff check src/           # Lint
uvx ruff format src/           # Format
```

### Code Style

- **Safety > Performance > DX** (in that priority order)
- Aggressive assertions: validate inputs, outputs, and state (~2 per function)
- Split assertions: `assert a; assert b` not `assert a and b`
- Assert negative space: all `if/elif` chains need a final `else` with `assert False`
- Functions must be <= 70 lines
- No recursion; prefer simple loops
- No abbreviations in names (`user` not `usr`)
- Comments explain "why", not "what"
- All lines <= 100 columns

### Adding a New Tool

1. Add the data-fetching method to `LibrusManager` in `src/librus_client.py`:
   - Use `cls._execute(alias, library_function, *args)` for automatic retry.
   - Add input assertions and post-condition assertions.
2. Add the MCP tool function in `src/server.py`:
   - Decorate with `@mcp.tool()`.
   - Add input assertions (`assert student_alias`, `assert isinstance(...)`).
   - Convert output via `to_dict()` if it contains dataclasses.
3. Update the tools table in `README.md`.

### Adding a Patch

If you find a bug in `librus-apix` that needs a runtime fix:

1. Add the patched function to `src/patches.py`.
2. Apply it in `apply_patches()`.
3. Add a comment explaining the original bug and what the patch changes.
4. Consider upstreaming the fix to [librus-apix](https://github.com/RustySnek/librus-apix).

### Configuration

Credentials are loaded by `src/config.py` in this priority order:

1. **`LIBRUS_ACCOUNTS` env var** — a JSON array of `{alias, username, password}` objects. Best for `uvx` users.
2. **`LIBRUS_CONFIG` env var** — absolute path to a `secrets.json` file. Best for custom locations.
3. **`secrets.json` in CWD** — then project root as fallback. Best for local development.

The schema is defined by `AppConfig` and `AccountConfig` Pydantic models in `src/config.py`. The template is in `secrets.json.template`.

**Never commit `secrets.json`.** It contains plaintext Librus credentials.

## Testing

Run the verification script to test authentication and basic data fetching:

```bash
python verify_connection.py
```

There is no automated test suite yet. When adding one, use `pytest` and mock the `librus_apix` calls to avoid hitting the real Librus API.

## Important Constraints

- **stdout is the MCP transport channel.** Never `print()` to stdout. Use `sys.stderr` or `logging` for diagnostics.
- **secrets.json must never be committed.** It is in `.gitignore`.
- **librus-apix is a scraper**, not an official API. It can break when Librus updates their HTML. If tools start failing, check for librus-apix updates first.
