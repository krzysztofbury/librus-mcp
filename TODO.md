# TODO

## 0.6.0: Immediate Safety Fixes

- [x] Prevent `send_message` from retrying a non-idempotent POST after an
  authentication failure. Return an uncertain-delivery error instead.
- [x] Return `status: "failed"` when Librus rejects a message.
- [x] Apply explicit request deadlines to requests-based upstream calls and
  operation deadlines to every upstream call, not only attachment downloads.
- [x] Restrict attendance and homework detail references to Librus-issued IDs
  so relative-path traversal cannot reach arbitrary authenticated routes.
- [x] Serialize notification read/diff/write transactions across separate MCP
  processes that share a state directory.

## Safety Hardening

- [x] Use the full SHA-256 alias digest for sanitized notification state paths.
- [x] Write attachments through an exclusive temporary file and atomic publish
  so interrupted writes cannot leave a partial final file.
- [x] Apply login cooldowns only to authentication or confirmed throttling
  failures, not transient network errors.
- [x] Document that the send confirmation token is an interlock, while human
  approval is enforced by MCP hosts through destructive-tool annotations.

## Tooling

- [ ] Triage the 71 findings ruff 0.16 reports under its widened default rule
  set (SIM117, RUF012, I001, TRY004, DTZ005, DTZ007, UP006/UP035/UP041/UP045,
  PYI036, BLE001) and decide which to adopt in `[tool.ruff.lint] select`.
  DTZ005/DTZ007 (naive datetimes) and BLE001 (blind except) are the ones worth
  reading first.

## MCP Contract

- [ ] Add typed output schemas for collection tools that still return `Any`.
- [ ] Add an integration fixture for a populated behaviour-notes page.
- [x] Add populated multi-page fixtures for received messages and completed
  lessons, covering first-page reuse and the final page.

## Delivery And Compatibility

- [x] Test the supported Python version in CI (3.14).
- [ ] Resolve the GPL-3.0 repository license versus MIT PyPI metadata for
  `librus-apix` before the next public release.
