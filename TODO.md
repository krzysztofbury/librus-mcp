# TODO

This roadmap records the native 2.0 implementation and the historical 1.x work
that preceded it. Version numbers indicate compatibility risk, not a release
commitment:

- Compatible work (`1.x`): additive response schemas, bounded UX,
  resource controls, safety fixes, and documentation.
- Major release (`2.0.0`): deliberate tool, response, package, or configuration contract changes.

## Active 2.0.0 Plan

The direct native-backend migration is planned in
[MCP_2_0_PLAN.md](MCP_2_0_PLAN.md), based on remote MCP main `0aaf658` and API
main `01b32e0` reviewed on 2026-10-05. Work branch: `feat/2.0.0-native-api`.
API `1.0.2` is on PyPI and pinned. Native consumer integration, declared hosted
platform profiles and MIT review are qualified; MCP publication remains open.

- [x] Review both main branches, the API's native cutover matrix and all 18
  existing MCP 2.0 roadmap items; create the dedicated MCP branch.
- [x] File API gaps [#22-27](https://github.com/krzysztofbury/librus-python-api/issues)
  with evidence and acceptance criteria; distinguish required and conditional gates.
- [x] Approve W0 contract choices: backend/platform scope, tool catalog,
  poll/ack delivery, context key, configuration and migration/rollback policy.
- [x] W1: API #22-25 are closed and included in published stable API `1.0.0`,
  pinned for native development. Consumer acceptance of durable integrations
  remains part of W4/W5; upstream completion alone is not MCP qualification.
- [x] W2: establish `librus_mcp` packaging, native lifespan and explicit config.
  Package/entry point, shared service, XDG selection, persistent-key input and
  offline validation and explicit doctor/storage diagnostics are implemented;
  platform acceptance is tracked under W7, including hardened Windows config ACLs.
- [x] W3: replace ordinary reads with native typed operations and MCP 2.0 DTOs.
  All planned ordinary read families, date windows, bound school references and
  presentation/native cursors pass family-wide offline stdio proof. Both catalogs
  pass the client's schema validators and numeric byte budgets.
- [x] W4: integrate native messaging, durable sends, streams and file publication.
  Message summaries/content and recipient discovery/selection are implemented,
  with explicit backend/context binding and received-open consent. Both backends
  pass stdio/restart send/read/file proof, including cancellation/disconnect and
  post-publication snapshot fallback. Final platform acceptance is tracked in W7.
- [x] W5: implement notification poll/status/ack and explicit old-state migration.
  Poll/status/ack, POSIX old-file inventory/reviewed bootstrap, per-account old-state
  quarantine, explicit archive export and loss-consenting recovery are integrated.
  Historical event replay/ack and malformed checkpoint retention pass offline
  restart proof, collision/capacity rejection, interrupted manifests and explicit
  uncertainty recovery. Lossless reverse migration is not promised.
- [x] W6: remove apix and duplicated runtime HTTP/parsers/workers/caches/JSON state.
  Historical source/tests/tooling are preserved, GPL-scoped and excluded from
  imports/builds in `legacy_reference/`. Cosmic Ray is removed from native dev deps.
- [x] W7: qualify installed artifacts, protocol contracts, representative workloads,
  declared platforms and the source/dependency provenance required for MIT.
  Local isolated MIT wheel-from-sdist passes 73 tests (1 Windows-only skip), CLI,
  both catalog profiles and artifact inventories. MIT source/dependency review is
  recorded in `LICENSE_REVIEW.md`. Run `37372839458` passed at `bc10abe`: Linux and
  macOS 73 passed/1 skip each; Windows 56 passed/18 declared-profile skips,
  including executed private/shared credential ACL and hardlink guards.
  No performance improvement or unapproved live side-effect compatibility is claimed.
- [ ] W8: publish the exact API prerequisite and MCP 2.0.0, verify remote artifacts
  and fresh `uvx` startup.
  API `1.0.2` (bounded subject frequency, faster request policy) is the pinned prerequisite. The
  publishing workflow runs native lint, strict typing and audited sdist rebuild
  with installed consumer acceptance. Setup no longer needs operator steps: the
  context key, private permissions and 1.x notification state are handled on
  first start. Version is `2.0.0`; tag, publication and remote install
  verification remain.

Parked by the owner: API #26 (notes/observation cards, missing qualifying examples)
and #27 (daily credentialed CI, noncritical). Neither blocks MCP 2.0.0. Notes
remain unavailable/unregistered; offline E2E and release qualification remain required.

The target is a thin MCP client with reusable heavy work in `librus-python-api`.
New tool requests/responses may break 1.x compatibility. Durable history and
uncertain sends must remain recoverable. MIT is the license of the new native
2.0 release; existing GPL releases and notices are not retroactively changed.
The release candidate is `2.0.0`; dependency replacement is complete with no
apix fallback. Hosted acceptance is complete for the declared
profiles; PR #39 remains draft and unmerged. Publication requires separate approval.

## Historical 1.x Roadmap

The foundations and compatible follow-ups below describe the shipped 1.x line,
not the native 2.0 implementation. Their old tool names, shapes, mutation tooling
and catalog sizes are historical evidence. Native proof ownership is in
[NATIVE_TEST_PLAN.md](NATIVE_TEST_PLAN.md); the major-release checklist below
records implemented replacements and explicit scope differences.

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
  Superseded for 2.0: behaviour notes are not provided; populated contracts are
  tracked as API #26, parked by the owner.
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

## Major Release (2.0.0): Reconciled Implementation Checklist

### Stable Domain-Oriented Tool Contract

All A01-A18 have implemented outcomes in the plan's
[readiness map](MCP_2_0_PLAN.md#7-all-18-mcp-20-todo-items). A checked item means the
documented native outcome below, not preservation of every illustrative label or
1.x response shape. W8 publication remains unchecked in the active plan above.

- [x] A01: standardize collection envelopes with `items`, typed pagination,
  truncation and observations; retain family metadata and best-effort consistency,
  never claim transactional snapshots.
- [x] A02: replace dynamic subject, recipient and schedule maps with typed record arrays.
- [x] A03: preserve stable normalized detail keys alongside raw labels and unknown keys.
- [x] A04: expose native `ratio` in 0..1/null and count fields, not converted percentages.
- [x] A05: rename `sort_by` to `scope` because it filters rather than sorts.
- [x] A06: replace raw route arguments with numeric `attendance_id`, bound
  `homework_ref` and bound `event_ref`.
- [x] A07: use bounded integer `year` and `month` inputs and consistent `date_from` and
  `date_to` names across tools.
- [x] A08: introduce closed native error categories and MCP input/internal errors,
  with redaction and explicit uncertain delivery; illustrative old names are not
  the authoritative codes.
- [x] A09: remove deprecated `all_pages`; use bounded cursor/window operations.
- [x] A10: replace standalone read-once reads with consent-gated durable
  notification polling, explicit acknowledgement and offline recovery.

### Package And Configuration Cleanup

- [x] A11: move the generic top-level `src` package to `src/librus_mcp` and update the
  console entry point to `librus_mcp.cli:main`, preserving version/config/doctor routing.
- [x] A12: replace Cosmic Ray with the optional POSIX mutmut 3 campaign for native
  MCP-owned safety boundaries. Real stdio instrumentation, baseline and survivor
  review are documented in [MUTATION_TESTING.md](MUTATION_TESTING.md).
- [x] A13: prefer an explicit `LIBRUS_CONFIG` or XDG configuration path over silently
  discovering a generic `secrets.json` in the current working directory.
- [x] A14: document explicit config/key/state migration and recovery before removing cwd discovery.
  Serving now also provisions the key and permissions and adopts 1.x state itself.
- [x] A15: retire legacy mirror writes immediately in the breaking native cutover;
  old mirrors are adoption/import inputs, archived to `legacy-1x`, never a fallback.
- [x] A16: reject legacy collisions/conflicts before bootstrap; never silently rebind aliases.

### Attachment Delivery Contract

- [x] A17: expose bounded POSIX attachment snapshots where supported; keep complete
  server-local files as the explicit Windows/host/capacity/expiry fallback.
- [x] A18: keep explicit byte limits and avoid placing large attachment content directly
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
