# TODO

This roadmap tracks remaining work after 1.7.0. Each work group can be
delivered independently. Version numbers below indicate compatibility risk,
not a release commitment:

- Compatible work (`1.x`): additive response schemas, bounded UX,
  resource controls, safety fixes, and documentation.
- Major release (`2.0.0`): deliberate tool, response, package, or configuration contract changes.

## Remaining Work After 1.7.0

Preserve the existing text response shapes and feature gates until a documented
2.0 migration. The populated behaviour-note fixture is deliberately deferred;
behaviour notes remain experimental and disabled by default.

Next independent batch: anonymize a populated behaviour-note page when one is
available, before enabling the feature by default.

## Completed Safety Foundations (1.2.x)

### Release Compliance

- [x] Resolve the GPL-3.0 repository license versus MIT PyPI metadata for
  `librus-apix` conservatively by licensing this project as GPL-3.0-only.
- [x] Record the upstream licensing conclusion in the README and package metadata.
- [x] Disclose the upstream metadata conflict and the reason for the license choice.

### Notification Correctness

- [x] Treat recently added schedule events as read-once data rather than a
  read-only, idempotent endpoint.
- [x] Make `get_recent_schedule_events` state-mutating in its MCP annotations and
  document that reading the events consumes them upstream.
- [x] Persist a durable pending notification result immediately after consuming
  read-once schedule events, before further parsing or state updates can fail.
- [x] Add tests for cancellation and state-save failure after schedule events are fetched.

### Security Verification

- [x] Establish a Cosmic Ray mutation baseline for authentication and local-state
  safety invariants before changing those paths; require targeted mutants to be killed.

### Authentication Failure Control

- [x] Distinguish an expired session from a persistent endpoint authorization denial.
- [x] Evict the newly authenticated client after a second authentication-class failure.
- [x] Add a short per-alias and per-operation cooldown for persistent access denial.
- [x] Test repeated calls to a permanently denied endpoint and bound login attempts.

### Configuration And Local-State Safety

- [x] Hide credential values in Pydantic validation errors and emit one redacted,
  actionable startup error without a traceback.
- [x] Store passwords as `SecretStr` and unwrap them only at the authentication boundary.
- [x] Warn or fail when a POSIX credential file is readable by group or other users.
- [x] Update setup instructions to create credential files with mode `0600` and
  recommend a global file outside project workspaces.
- [x] Create notification state directories as `0700` and state files as `0600`.
- [x] Bound notification state file size, list length, ID type, and ID length before parsing.
- [x] Normalize or reject surrounding alias whitespace, bound alias length, and
  reject unknown `AccountConfig` keys.
- [x] Centralize all operator-facing environment variables, defaults, and source
  precedence in `config.py`; pass effective paths to feature modules.

### Input And Response Bounds

- [x] Add a central maximum response-body size for requests and gateway responses,
  including chunked responses.
- [x] Bound recently added schedule events before or during parsing without silently
  dropping data already consumed from the read-once upstream endpoint.
- [x] Enforce collection item limits independently of page-count assumptions.
- [x] Reject or truncate message pages larger than the expected page size and
  report `truncated=true` when applicable.
- [x] Bound attendance records and unique lesson and subject IDs before creating tasks.
- [x] Add title, content, recipient ID, and total payload limits to `send_message`.
- [x] Require numeric, unique recipient IDs in both the MCP schema and runtime validation.
- [x] Reject reversed `get_subject_frequency` date ranges.
- [x] Correct the completed-lessons page boundary so the configured maximum is a
  page count rather than a last-page index.
- [x] Add oversized body, oversized collection, malformed recipient, and boundary tests.

### Parser And Download Safety

- [x] Replace assertions that validate external HTML or JSON with explicit parse errors.
- [x] Require a minimum populated behaviour-note field set instead of producing
  notes with empty date or content fields.
- [x] Decide whether behaviour notes remain default-on; otherwise mark the feature
  experimental and default it off until the populated fixture is verified.
- [x] Add cooperative cancellation to attachment downloads and check it before
  atomically publishing the final file.
- [x] Test that a cancelled or timed-out download cannot publish a file later.

### Release Verification

- [x] Check the release tag against `project.version` before publishing.
- [x] Run lockfile, lint, test, and build checks in the publishing workflow.
- [x] Install the built wheel in a clean environment and smoke-test its console entry point.
- [x] Pin third-party GitHub Actions to commit SHAs.
- [x] Align CONTRIBUTING setup and verification commands with CI and SPEC.

## Compatible Follow-ups (1.3.x or 1.4.x)

### Parser And Download Safety

- [ ] Add an anonymized integration fixture for a populated behaviour-notes page.
- [x] Reproduce `get_final_grades` parse failures with a grades-table fixture
  containing synthetic values and restore merged behaviour-summary parsing.
- [x] Reproduce the `get_subject_frequency` `CookieConflictError` with synthetic
  session cookies and restore read-only access without weakening cookie isolation.

### Typed MCP Output Contracts

- [x] Add server-owned Pydantic output models for collection tools that
  previously returned `Any`, including optional read and download tools.
- [x] Document the existing response shapes before publishing schemas, retaining
  legacy text content and recording the SDK's new structuredContent shape.
- [x] Require known fields in message content and attendance-frequency outputs.
- [x] Publish discriminated non-error outputs for send preview, sent, and failed;
  keep uncertain delivery as an actionable MCP error without structured content
  or automatic retry (output schemas do not cover `isError` responses).
- [x] Snapshot every tool input schema, output schema, and annotation through
  stdio for both the default and all-feature profiles.
- [x] Add stdio integration tests for `initialize`, `tools/list`, and representative
  `tools/call` responses, including `structuredContent`.

### Bounded Collection UX

- [x] Add `limit`, `max_pages`, and continuation metadata to `get_messages`,
  including an offset for partial pages.
- [x] Add a separate bounded completed-lessons tool without changing the
  legacy list response shape.
- [x] Add compact or date-bounded modes to other large collections.
- [x] Keep `all_pages` for compatibility and recommend explicit bounded requests
  for new clients.
- [x] Apply a whole-tool deadline to multi-page messages and completed lessons.
- [x] Deduplicate received messages by validated ID and detect repeated page signatures.
- [x] Report detected mailbox changes during pagination without claiming stable snapshots.
- [x] Add compact or date-bounded modes for grades and attendance.
- [x] Add category filtering to notifications without advancing unrequested category state.

### Runtime Resource Control

- [x] Replace per-call notification executors with one process-wide bounded executor
  or work queue.
- [x] Add aggregate concurrency tests across multiple student aliases.
- [x] Move notification state reads and writes off the MCP event loop while preserving locks.
- [x] Add a bounded per-client cache for lesson-to-subject and subject-to-name metadata.
- [x] Reuse pagination metadata from the requested message page instead of fetching
  and parsing page zero first for every nonzero page request.
- [x] Add call-count and cache-eviction tests across consecutive requests.

### Setup And Diagnostics UX

- [x] Add `librus-mcp --version`, `librus-mcp --check-config`, and
  `librus-mcp doctor` commands that never print credentials.
- [x] Add an optional `doctor --live` mode for explicit authentication and read checks.
- [x] Recommend a version-pinned `uvx librus-mcp==<version>` configuration and
  document deliberate upgrades and a track-latest alternative.
- [x] Document GUI-client PATH troubleshooting and use of an absolute `uvx` path.
- [x] Publish MCP-client setup evidence and an OS installed-wheel smoke-test matrix.
- [x] State explicitly that the server is local stdio only and that downloaded
  attachment paths refer to the server process machine.
- [x] Document reconnect or restart requirements after configuration changes.

### Tool Discovery Efficiency

- [x] Shorten repetitive tool descriptions while preserving constraints and
  actionable usage guidance in the published catalog.
- [x] Measure and record default and opt-in `tools/list` sizes, with a CI context
  budget to catch uncontrolled growth; see `MCP_CONTRACT.md`.
- [x] Evaluate optional feature profiles that expose only the tools a deployment uses.
  Defer an extra configuration gate while the expanded 24/28-tool catalogs stay
  below the existing 48/64 KiB budgets; existing feature gates remain available.

## Major Release (2.0.0)

### Stable Domain-Oriented Tool Contract

- [ ] Standardize collection responses on one envelope with `items`, pagination,
  truncation, and snapshot metadata.
- [ ] Replace dynamic subject, recipient, and schedule maps with arrays of typed records.
- [ ] Normalize upstream Polish labels into stable keys while retaining optional raw fields.
- [ ] Standardize attendance values on percentages, or encode ratio and percentage
  units explicitly in field names and bounds.
- [ ] Rename `sort_by` to `scope` because it filters rather than sorts.
- [ ] Rename `detail_url` to `attendance_id` or `homework_id` and `href` to `event_ref`.
- [ ] Use bounded integer `year` and `month` inputs and consistent `date_from` and
  `date_to` names across tools.
- [ ] Introduce stable error categories such as `CONFIG_INVALID`, `AUTH_FAILED`,
  `UPSTREAM_TIMEOUT`, `LAYOUT_CHANGED`, and `DELIVERY_UNKNOWN`.
- [ ] Remove the deprecated `all_pages` mode after bounded pagination is established.
- [ ] Remove or replace the standalone read-once schedule-events tool once consumers
  have migrated to stateful notifications.

### Package And Configuration Cleanup

- [ ] Move the generic top-level `src` package to `src/librus_mcp` and update the
  console entry point to `librus_mcp.server:main`.
- [ ] Replace Cosmic Ray with mutmut 3 after removing the unsupported `src`
  import package name.
- [ ] Prefer an explicit `LIBRUS_CONFIG` or XDG configuration path over silently
  discovering a generic `secrets.json` in the current working directory.
- [ ] Provide a documented migration path before removing current-directory config discovery.
- [ ] Remove the legacy eight-character notification-state mirror after its migration window.
- [ ] Reject any remaining legacy state-path collisions before compatibility support is removed.

### Attachment Delivery Contract

- [ ] Evaluate exposing downloaded attachments as MCP resources where host support
  permits it instead of returning only a server-local absolute path.
- [ ] Keep explicit byte limits and avoid placing large attachment content directly
  into the agent context.

## Completed Work

- [x] Prevent `send_message` from retrying a non-idempotent POST after an
  authentication failure and return an uncertain-delivery error instead.
- [x] Return `status: "failed"` when Librus rejects a message.
- [x] Apply request and operation deadlines to all upstream calls.
- [x] Restrict attendance and homework detail references to Librus-issued numeric IDs.
- [x] Serialize notification read, diff, and write transactions across MCP processes.
- [x] Use the full SHA-256 alias digest for sanitized notification state paths.
- [x] Write attachments through an exclusive temporary file and atomic publish.
- [x] Apply login cooldowns only to authentication or confirmed throttling failures.
- [x] Document the send confirmation token trust-model limitation.
- [x] Adopt the selected ruff 0.16 checks without enabling high-churn rule families.
- [x] Add typed output schemas for messaging recipient groups and recipients.
- [x] Add populated multi-page fixtures for received messages and completed lessons.
- [x] Test the supported Python version, Python 3.14, in CI.
