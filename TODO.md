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

- [ ] Use the full SHA-256 alias digest for sanitized notification state paths.
- [ ] Write attachments through an exclusive temporary file and atomic rename
  so interrupted writes cannot leave a partial final file.
- [ ] Apply login cooldowns only to authentication or confirmed throttling
  failures, not transient network errors.
- [ ] Document that the send confirmation token is an interlock, while human
  approval is enforced by MCP hosts through destructive-tool annotations.

## MCP Contract

- [ ] Add typed output schemas for collection tools that still return `Any`.
- [ ] Add an integration fixture for a populated behaviour-notes page.

## Delivery And Compatibility

- [x] Test the supported Python versions in CI (3.10 through 3.13).
- [ ] Resolve the GPL-3.0 repository license versus MIT PyPI metadata for
  `librus-apix` before the next public release.
