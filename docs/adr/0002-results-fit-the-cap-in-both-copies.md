# 2. Results fit the 512 KiB cap in both copies

## Context

The server rejects a whole `CallToolResult` above 512 KiB with `LIMIT`
(`presentation.py`, `MAX_RESULT_BYTES`). Each result is sent twice: as
`structuredContent` and as the same JSON escaped into a text block. A quote
costs 2 bytes in `structuredContent` and 4 in the escaped text copy, so school
text can cost several times its length on the wire.

The API accepts a 256 KiB page with up to 262144 characters of text (#90).
Four such announcements, returned at once, were about 960 KiB and failed with
`LIMIT`.

## Decision

- Pages of tools whose single items can be large end by size as well as by
  count (`SizedWindowPagination`). Each item is measured as its JSON in both
  copies, against the cap less a reserve for identity, observation,
  pagination and the result envelope (`_ENVELOPE_RESERVE`).
- The first item of a page is always returned, so a long collection never
  blocks its later items.
- The notification store bounds staging before any side effect, leaving room
  for escaping and SDK formatting under the full wire cap (`runtime.py`).

## Consequences

- Long school text arrives page by page instead of failing
  (`test_read_boundaries.py`, `test_school_paging.py`).
- An item larger than the whole budget on its own still fails as `LIMIT`.
- A change to the result's copies (for example dropping the text copy) must
  revisit this budget.
