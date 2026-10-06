# MCP 2.0 protocol contract

All earlier MCP versions use apix. This native contract intentionally breaks 1.x
tool names/arguments, responses, configuration and durable workflows. There is no
compatibility adapter. See [MIGRATION_2_0.md](MIGRATION_2_0.md).

## Catalog and results

`tools/list` is authoritative, generated from `librus_mcp` annotations. Every input
and output schema is checked with the client's JSON Schema validator, including
representative reference/cursor payloads. All 26 default tools (including
notifications and attachments) have typed outputs. Enabling sending gives 30
tools; disabling notifications and attachments leaves 22. Behaviour notes
remain unregistered. Catalog listing is offline and does not authenticate.

```bash
uv run python release_verification/measure_tools.py
uv run python release_verification/measure_tools.py --all-features
```

The default and all-feature UTF-8 catalog budgets are both 128 KiB. They count
descriptions, annotations, inputs and outputs. These are context-size gates, not
performance claims. The text block of a typed result is the same JSON value as
`structuredContent`, serialized compactly (UTF-8, no indentation) because many
hosts place it in model context. The complete result, including both
serializations, must fit 512 KiB or return `LIMIT`, never silently truncate.

Responses preserve native typed arrays, observations and explicit availability.
Attendance ratios use `0..1` or null, never inferred percentages. Collection
continuation is best effort, account/context/query-bound, and returns explicit
cursor/truncation information. Whole grade/attendance reads page by `limit`
(default 100) like the date-window tools, so results stay bounded by design. References are inert identifiers, not upstream URLs.

Domain/protocol errors return `isError=true` and
`{"error":{"code":"CLOSED_CODE"}}`. No validation inputs, credentials, tokens,
HTML, causes or raw exception text are included. Unanticipated errors are
`INTERNAL_ERROR`. Unsupported capability and valid empty results are distinct.

## Side effects and consent

Read-only annotations distinguish local reads, upstream reads and session/view
selection. Catalog annotations are hints, not an authorization mechanism.

- Received-body reads require `allow_mark_read=true`; sent-body reads do not.
- Sending is opt-in. `preview_message` persists an exact payload binding without
  HTTP. Redemption additionally requires `confirm=true` and actual human approval.
  Tokens do not prove approval. Cancellation, lost responses and uncertain native
  outcomes never trigger consumer retries. Inspect `get_send_outcome`/history.
- Notification polling is on by default and durably stages delivery. A returned receipt
  must be acknowledged only after delivery. Pending batches replay across process
  restart. Fresh agenda consumption additionally requires
  `allow_consume_events=true`. Malformed checkpoints and uncertain reservations are
  preserved. Explicit POSIX operator recovery can accept possible event loss.
- Attachment download is on by default and does not open a message body. Native file
  publication is the commit point. Optional POSIX snapshots are inert, bounded,
  expiring and runtime-only. A snapshot failure returns the published local file
  and digest without a URI. Windows currently returns local files only.

Modern and legacy backends are selected per account, without fallback. Modern
hierarchical recipient choices return `UNSUPPORTED_CAPABILITY`; ordinary modern
recipient discovery remains supported. Supplied references, selections and cursors
must match the configured backend, account and persistent context.

All school text is untrusted data, not instructions. No new 1.x compatibility
release is inserted. Old state requires reviewed explicit bootstrap; downgrade is
not automatic or promised lossless after native writes.
