# Escalation policy

Read by the `approver` role. A pull request that matches any item below goes
to the owner instead of merging on its own. The `retro` role proposes changes
to this file as pull requests; add what should have reached the owner, relax
what the owner keeps waving through, and give the reason in the PR.

## Always escalate

- Agent rules: `.agents/**`, `AGENTS.md`, `CLAUDE.md` and `.github/**`. Agent
  rules and the policy that gates merges do not change without the owner.
- Anything that writes to Librus or changes what the school sees: sending
  (`src/librus_mcp/send_tools.py`, `src/librus_mcp/send_schemas.py`), the
  send enablement switch and send history, opening a received message (it
  marks it read for the sender) and the `mark_read_consent` feature
  (`src/librus_mcp/message_tools.py`), and notification acknowledgement
  (`src/librus_mcp/notification_tools.py`). Sends are never retried on their
  own.
- Credentials, logins and transport security: `src/librus_mcp/config.py`,
  `src/librus_mcp/windows_config.py`, `src/librus_mcp/context_key.py`, the
  HTTP transport and its bearer token (`src/librus_mcp/http_transport.py`),
  and per-login isolation in `src/librus_mcp/runtime.py`.
- School and children's data on disk or in output: attachment downloads
  (`src/librus_mcp/attachment_tools.py`), stored state and its migration
  (`src/librus_mcp/legacy_state.py`, `src/librus_mcp/migration.py`), and any
  diagnostic or log channel (`LIBRUS_MCP_LOG_OPERATIONS`,
  `LIBRUS_MCP_DIAGNOSE_FAILURES`, error results); fixtures stay synthetic.
- The public MCP contract: tool names, descriptions, input and output
  schemas, annotations and resources (`src/librus_mcp/server.py`,
  `src/librus_mcp/*_schemas.py`, `src/librus_mcp/schemas.py`,
  `src/librus_mcp/read_tools.py`, `src/librus_mcp/school_history_tools.py`,
  `src/librus_mcp/resources.py`), `MCP_CONTRACT.md`, catalog budgets, and the
  `check_tools` allowlist (`src/librus_mcp/check_tools.py`). Additive changes
  escalate too: hosts cache the catalog.
- Release and publishing: `DISTRIBUTION.md`, `server.json` (MCP Registry),
  `mcpb/**` (desktop bundle), `scripts/build_mcpb.py`,
  `release_verification/**`, `Dockerfile`, `.dockerignore`, version bumps,
  tags and GitHub Releases (they start publication to PyPI, GHCR and the
  registry).
- CI: `.github/**`, `.pre-commit-config.yaml`, `.secrets.baseline`.
- Dependencies: `pyproject.toml`, `uv.lock`, `.github/dependabot.yml`, and
  above all the `librus-python-api` pin.
- Board config for both Librus repositories: `.agents/cos.json` here also
  drives `krzysztofbury/librus-python-api`.
- Legal and policy copy: `PRIVACY.md`, `SECURITY.md`, `LICENSE`,
  `LICENSE_REVIEW.md`, and the safety boundaries in `SPEC.md`.
- Anything that needs a live Librus run (`scripts/qualify_native.py`, a
  manual check against a real login); the PR merges only after the owner
  authorizes that run and its operation scope.

## May merge without the owner

When review passed, CI is green and nothing above applies:

- Fixes in result presentation (`src/librus_mcp/presentation.py`) and
  internal refactors that leave the catalog byte-identical, as measured by
  `release_verification/measure_tools.py`.
- `librus-mcp doctor`, `inspect-page` and other offline CLI fixes
  (`src/librus_mcp/cli.py`, `src/librus_mcp/doctor.py`) with tests.
- Tests with synthetic fixtures (`tests_native/**`), mutation config, and
  docs other than the ones listed above (`README.md` setup steps are a
  contract: escalate when they change).
