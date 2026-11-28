# 1. Offset-free school time in published schemas

## Context

Librus shows school wall times (lesson times, observation times) without a UTC
offset. `librus-python-api` keeps them that way rather than guessing a
daylight-saving fold, so Pydantic serialises them without an offset.

JSON Schema's `"date-time"` and `"time"` formats follow RFC 3339, which
requires an offset. Hosts that validate results strictly (for example with
`ajv-formats`) rejected such results. Python's `jsonschema` skips
`"date-time"` unless the optional `rfc3339-validator` is installed, and its
built-in `"time"` check accepts offset-free values, so a test using it alone
would not notice.

## Decision

- Present civil time verbatim in the native ISO format, never converted to UTC
  (`read_schemas.py`, `at_time`).
- Publish timestamps with a pattern for the ISO 8601 shape Pydantic emits,
  with the offset optional, instead of `"format": "date-time"` or `"time"`
  (`server.py`, `_ISO_DATE_TIME`).
- Write that pattern with plain groups, not `(?:`, to stay in JSON Schema's
  recommended regex subset and to save bytes in every tool that returns a
  timestamp.
- Tests check results with an RFC 3339 checker equivalent to `ajv-formats`
  (`tests_native/published_schema.py`), and the catalog test checks that the
  pattern accepts offset-free wall times (`test_catalog_schema.py`).

## Consequences

- Results with offset-free times validate on strict hosts.
- A change to how the API serialises times must update the pattern and its
  tests together.
