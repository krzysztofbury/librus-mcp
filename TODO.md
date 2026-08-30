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
- [ ] Decode the attachment filename from `Content-Disposition` as UTF-8.
  `requests` decodes headers as latin-1, so `_filename_from_disposition` in
  `src/scraping.py` turns the bytes of `ą` (`c4 85`) into `Ä` plus `U+0085`,
  and the file lands on disk as `RzÄ<0x85>ska` instead of `Rząska`. Verified
  against a real message on 2026-08-21. File contents are correct, only the
  name is wrong. Also parse the RFC 5987 `filename*=UTF-8''` form, and reject
  control characters in `_safe_attachment_filename`, which today filters only
  `""`, `"."` and `".."`.

## MCP Contract

- [ ] Add typed output schemas for collection tools that still return `Any`.
- [ ] Add an integration fixture for a populated behaviour-notes page.
- [ ] Report the package version in `serverInfo`. `FastMCP("librus-mcp")` in
  `src/server.py` passes no version, so the handshake returns the `mcp` SDK
  version (`1.28.1`) and a client cannot tell which build it talks to.
- [x] Add populated multi-page fixtures for received messages and completed
  lessons, covering first-page reuse and the final page.

## Delivery And Compatibility

- [x] Test the supported Python version in CI (3.14).
- [ ] Resolve the GPL-3.0 repository license versus MIT PyPI metadata for
  `librus-apix` before the next public release.
