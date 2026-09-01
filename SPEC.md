# SPEC.md - Agent/Bot Specification for librus-mcp

This document describes how AI agents and bots should interact with this codebase.

## Project Overview

**librus-mcp** is an MCP (Model Context Protocol) server that wraps the [librus-apix](https://github.com/RustySnek/librus-apix) library to expose Librus Synergia gradebook data as tools for AI assistants.

- **Language:** Python 3.14+
- **Package manager:** [uv](https://github.com/astral-sh/uv) (preferred) or pip
- **Formatter/Linter:** [ruff](https://github.com/astral-sh/ruff) (line-length: 100, target: py314)
- **Build system:** hatchling
- **License:** MIT (note: upstream librus-apix ships GPL-3.0 in its repository
  but MIT in its PyPI metadata — an open upstream question tracked before releases)

## Architecture

```
src/
  server.py              - MCPServer (mcp 2.x) server. Defines all MCP tools. Entry point.
  librus_client.py       - LibrusManager class. Handles auth, caching, retry, and data fetching.
  config.py              - Reads secrets.json via Pydantic models (accounts, features, dirs).
  notification_state.py  - Per-alias persistence of seen-notification IDs (JSON files).
  scraping.py            - Own Synergia scraping: message attachments, behaviour notes (uwagi).
```

### Key Design Decisions

1. **All librus-apix calls are blocking** and run via `asyncio.to_thread()`.
2. **Client instances are cached** per student alias in `LibrusManager._instances`.
   Each client gets a **fresh cookie jar**: upstream `new_client()` shares one
   mutable default jar across all clients, which would leak one child's session
   cookies into another child's requests.
3. **Operations are serialized per alias** by `_client_locks`: `requests.Session`
   and the cookie jar are not thread-safe. Different aliases run concurrently.
   The session context is kept persistent despite librus-apix wrapping every
   request in `with client._session`, preserving TCP/TLS connection pooling.
   The notification operation is the sole internal exception: five read-only
   categories use independent cloned clients and at most three worker threads;
   schedule stays on the original client. Clones never share a mutable session
   or cookie jar, and the outer alias lock still excludes other operations.
4. **Token expiry is handled** by `_execute()`, which retries once on
   `AuthorizationError`, `TokenError` ("Brak dostępu" page), or `TokenKeyError`.
   `MaintananceError` and `ParseError` are normalized into actionable `RuntimeError`s.
5. **Config is loaded once** and cached in `LibrusManager._config_cache`.
   Aliases must be unique and non-blank (enforced by Pydantic validators).
6. **Dataclasses are converted** to dicts via `to_dict()` for JSON-RPC serialization.
7. **Every tool carries `ToolAnnotations`** (readOnly / destructive / idempotent /
   openWorld hints). `send_message` is destructive and uses a **two-step
   confirmation**: the first call returns a preview plus a single-use
   `confirm_token` (5-minute TTL, bound to the exact payload); only the second
   call with that token sends. Trust-model caveat: the gate is model-enforced —
   the same agent holds the token and could confirm without showing the human
   the preview. It pins the payload and forces a second deliberate call; it is
   not a hard human-approval gate (MCP elicitation would be, where supported).
8. **Optional tools are feature-gated.** Core tools use `@mcp.tool()`; optional tools are
   plain functions registered by `register_optional_tools()` in `main()` based on
   `config.features` (env override: `LIBRUS_FEATURES`). `send_message` defaults off.
9. **Notification state is persisted** per alias as JSON under `state_dir`
   (`LIBRUS_STATE_DIR` > config > `~/.librus-mcp/state`), written atomically.
   Aliases that need filename sanitization get a full SHA-256 suffix so distinct
   aliases cannot share a state file. During compatibility migration, the
   8-character state mirror and lock are retained so old and new MCP processes
   cannot lose each other's updates. First run diffs against empty IDs —
   never use `get_initial_notification_data`, it 403s on `/uczen/index` for
   parent (rodzic) accounts.
10. **Own scraping lives in `src/scraping.py`** for gaps in librus-apix
    (attachments, uwagi, final grades). Attachment download flow:
    `/wiadomosci/pobierz_zalacznik/{msg}/{file}` → 302 (not followed
    automatically) → Location validated as exactly `https://sandbox.librus.pl/GetFile/…`
     → GET `<key>/get` **without cookies**, streamed with a 50 MiB cap and a
     deadline, then atomically hard-linked from an exclusive temporary file
     (never overwrites; the download filesystem must support hard links).
11. **Expensive upstream wrappers are bounded and deduplicated.** Subject
    frequency resolves each unique lesson and subject once, with five gateway
    requests in flight, host-scoped cookies, disabled redirects, two attempts
    per request, and a 50-second resolution deadline. Received messages and
    completed lessons reuse the first response for both data and page count.

## How to Work With This Codebase

### Setup

```bash
uv sync
cp secrets.json.template secrets.json  # Then fill in credentials
```

### Running

```bash
uv run librus-mcp                       # Start the MCP server
uv run python verify_connection.py     # Live smoke test (real credentials)
```

### Linting, Formatting, Tests

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run pytest -q
```

### Code Style

- **Safety > Performance > DX** (in that priority order)
- **Untrusted input** (MCP tool arguments, config files, upstream HTML) is
  validated with explicit `raise ValueError(...)` — never `assert`, which
  vanishes under `python -O`
- **Internal invariants** (upstream return shapes, post-conditions) keep
  aggressive assertions (~2 per function); split compound assertions
- Constrain MCP inputs in the signature too: `Literal[...]`,
  `Annotated[int, Field(ge=..., le=...)]`, regex patterns for IDs and dates
- Functions must be <= 70 lines
- No recursion; prefer simple loops with asserted upper bounds
- No abbreviations in names (`user` not `usr`)
- Comments explain "why", not "what"
- All lines <= 100 columns

### Adding a New Tool

1. Add the data-fetching method to `LibrusManager` in `src/librus_client.py`:
   - Use `cls._execute(alias, library_function, *args)` for automatic retry and
     per-alias serialization.
   - Validate untrusted arguments with `ValueError`; assert upstream post-conditions.
2. Add the MCP tool function in `src/server.py`:
   - Decorate with `@mcp.tool(annotations=READ_ONLY)` (or the appropriate annotations).
   - Constrain inputs in the signature (`StudentAlias`, `MessageId`, `IsoDate`, `Literal`).
   - Convert output via `to_dict()` if it contains dataclasses.
3. Add tests in `tests/` (mock `LibrusManager._execute`; never hit the real API).
4. Update the tools table in `README.md` and `CHANGELOG.md`.

### Configuration

Credentials are loaded by `src/config.py` in this priority order:

1. **`LIBRUS_ACCOUNTS` env var** — a JSON array of `{alias, username, password}` objects. Best for `uvx` users.
2. **`LIBRUS_CONFIG` env var** — absolute path to a `secrets.json` file. Best for custom locations.
3. **`secrets.json` in CWD** — then project root as fallback. Best for local development.

The schema is defined by `AppConfig` and `AccountConfig` Pydantic models in `src/config.py`. The template is in `secrets.json.template`.

**Never commit `secrets.json`.** It contains plaintext Librus credentials.

## Testing

- **Unit tests:** `uv run pytest -q` — mocked, no network. CI runs them on every push/PR.
- **Live smoke test:** `uv run python verify_connection.py [--all-accounts]` —
  requires real credentials; exercises auth, grades, messages, and timetable.

## Important Constraints

- **stdout is the MCP transport channel.** Never `print()` to stdout. Use `sys.stderr` or `logging` for diagnostics.
- **secrets.json must never be committed.** It is in `.gitignore`.
- **librus-apix is a scraper**, not an official API. It can break when Librus updates their HTML. If tools start failing, check for librus-apix updates first.
- **Accounts requiring interactive 2FA are unsupported** — upstream librus-apix
  has no 2FA flow; such accounts fail at authentication.
