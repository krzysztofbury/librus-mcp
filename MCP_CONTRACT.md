# MCP 2.1 protocol contract

All MCP versions before 2.0 use apix. This native contract intentionally breaks 1.x
tool names/arguments, responses, configuration and durable workflows. There is no
compatibility adapter. See [MIGRATION_2_0.md](MIGRATION_2_0.md).

## Catalog and results

`tools/list` is authoritative, generated from `librus_mcp` annotations. Every input
and output schema is checked with the client's JSON Schema validator, including
representative reference/cursor payloads. All 31 default tools (including
notifications and attachments) have typed outputs. Enabling sending gives 35
tools; disabling notifications and attachments leaves 27. Behaviour notes
remain unregistered. Catalog listing is offline and does not authenticate.

```bash
uv run python release_verification/measure_tools.py
uv run python release_verification/measure_tools.py --all-features
```

The default and all-feature UTF-8 catalog budgets are 128 and 144 KiB. They count
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
`MODULE_UNAVAILABLE` means the school's product lacks a module; it is distinct
from `VIEW_DISABLED`, `ACCESS_DENIED` and parser failures.

## Additive 2.1 reads

- Grade `items` now include `record_type="formative"` with an `assessment` object
  containing the native subject, text, category, semester, day, assessment_type
  and detail_id. Numeric/descriptive items retain their existing fields and gain
  nullable `formative_id`. Match this against `assessment.detail_id` to recognize
  mirrors, not two independent grades. Observation cards are formative subjects;
  they are not the unsupported behaviour-notes feature. The page order is numeric,
  descriptive, then formative, under one limit and source-bound cursor. Date
  windows filter every variant. Native formative scope semantics are not proven;
  week/last-login scope must not be interpreted as a guarantee for formative rows.
  There are no new grade-detail fetches or formative notification payloads.
- `get_school_year_archive` returns paged `items` with `record_type="year"` or
  `"achievement"` and typed native `data`, years first. Default limit is 10.
  Raw behaviour cells, empty marks and `-` are preserved; archive `year_end` is
  not asserted to equal a current annual grade. Each call refreshes one native
  collection. A large individual year can still exceed the result cap and return
  `LIMIT`; text is never silently shortened.
- `get_class_free_days` returns paged native items (default limit 100). Dates and
  optional lesson bounds are preserved. Type IDs are opaque, not holiday names;
  absent lesson bounds do not establish an all-day event.
- `get_message_correspondents(folder)` and `get_teacher_subjects` page modern
  discovery data, with default limit 100. Correspondent references bind persistent
  context, account, modern backend and folder. Teacher identifiers and
  correspondent references are not send-recipient references.
- `get_message_unread_counts` returns `data` with native identity, observation,
  `current` and `archive` folder counters. It opens no bodies and neither polls nor
  acknowledges durable MCP notifications. Upstream counter names are preserved.
- Modern `get_messages` accepts `archived=false`, `correspondent=null` and
  `unread_only=false`. Repeat these query values with continuation cursors; all
  are bound in the native cursor. `unread_only=true` requires received/current
  mail. Archive filtering is unsupported. Results expose these selections and
  `archiving_in_progress` (informational, nullable outside archives). References
  carry `archived`; archive content opens fail without HTTP even with consent.
  Legacy accounts reject modern-only reads/options without backend fallback.

The four new paged collections use context/query/source-bound presentation cursors
and limits 1..256. They do not promise snapshots or cache whole histories in MCP.
2.0 message references/cursors default to current, unfiltered mail. Grade cursors
may become stale after upgrading because the presented source now includes new
fields/variants; restart the read. Configuration, context keys and native durable
stores need no migration for 2.1.

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
release is inserted. Eligible old state is adopted automatically on the first
notification poll; explicit operator recovery remains available. Downgrade is
not automatic or promised lossless after native writes.
