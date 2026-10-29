# Native migration verification ownership

## 2.5.1 lucky number and page summaries

2.5.1 pins API 1.8.1 and changes no successful result shape. `get_timetable`
accepts any date in the week; a received message opens without a separate
consent unless `mark_read_consent` is on, and a refused open returns
`CONSENT_REQUIRED`.

- `test_inspect_page_needs_no_configuration` also runs `inspect-page profile`
  through the CLI.
- `test_academic_stdio.py` reads a timetable by a Thursday and gets its week;
  an impossible calendar date stays `INVALID_INPUT` without a request.
- `test_message_stdio.py`: by default a received message opens without
  `allow_mark_read`; `false` returns `CONSENT_REQUIRED` with `requires` and
  dispatches nothing. With `mark_read_consent` the server instructions say so,
  an open without `true` is refused before dispatch and `true` opens it.
  `test_read_boundaries.py`: a binding failure stays `INVALID_INPUT` with or
  without consent.
- The catalog measures 123731 bytes for 31 default tools and 137062 bytes
  for 35 tools (116 more than 2.5.0: the `get_timetable` date and
  `get_message_content` descriptions and its nullable consent input).
- Authorized live run on the four owner logins with API 1.8.1 from source:
  `student_information` returned an available lucky number on all four (1.8.0
  returned unavailable), and the API release live check passed.

## 2.5.0 failure diagnostics

- `test_failure_stdio.py` serves a grade tooltip the parser rejects, with a
  marker in the subject and tooltip and an alias that looks like a name. The
  error result's `where` ends at `markup:tooltip_fields`, and neither the
  result nor the server's stderr contains the marker or the alias. With
  `LIBRUS_MCP_DIAGNOSE_FAILURES=1` stderr also holds the masked tooltip
  structure. `inspect-page` runs without configuration.
- `tests_native/errors.py` checks the diagnostic fields of every asserted
  error result: code locations only, a class name, both versions.
- `test_output_schemas_accept_fields_a_later_release_adds`: no published
  output schema has `additionalProperties: false`; input schemas keep it.
- The 2.4 report reproduced: a 2.4.1 grade result fails validation against the
  2.3.1 catalog (`point_results`, `record_type: "point"`) and passes against
  2.4.x, matching the tester's `Invalid structured content` error.
- The catalog measures 123615 bytes for 31 default tools and 136927 bytes for
  35 tools.
- Authorized live run on the four owner logins with the published API 1.8.0:
  `qualify_native.py --live` academic 58 passed, 4 `VIEW_DISABLED`, 6 without
  a reference (122 requests, 20 more than 2.4.1: the gateway reads of the one
  new-schema login, two logins); communication 22 passed, 2 without a sent
  reference, 4 expected unsupported; homework_history 10 passed, 2 without a
  reference; v21 81 passed. `check-tools` with `LIBRUS_MCP_LOG_OPERATIONS=1`:
  20 tool calls OK, 20 operation lines, no alias or login in either output.

## 2.4.1 grade fixes

2.4.1 pins API 1.7.1 and changes no tool, input or result shape.

- The real point-grade page relayed by the school that reported 2.4.0 parses
  offline through the API and the MCP item mapping: 19 `point` items, one
  `numeric` formative mirror with its `formative_id`, 63 `point_results` and
  21 final summaries. The page is not committed; API 1.7.1 has original
  fixtures that follow its structure.
- An authorized live read found two owner logins failing every grade tool
  with `PARSE` on 2.4.0, from a multi-line teacher comment. On 2.4.1,
  `scripts/qualify_native.py --live --phase academic` passed every grade tool
  on all four logins: 58 passed, 4 `VIEW_DISABLED` (completed lessons, as
  before) and 6 detail checks without a reference, 102 requests.
- The catalog is unchanged: 126051 bytes for 31 default tools and 139595 bytes
  for 35 tools.

## 2.4.0 point grades

API 1.7.0 reads the "Oceny punktowe" table; MCP 2.4.0 adds the `point`
grade record type. The cause, both grade reads failing with `PARSE`, was
reproduced offline from a relayed screenshot: the point table is a second
table with current-grade headers, and an annual title in it made the summary
read ambiguous too.

- `test_point_grades_are_scores_with_their_period_result` serves an original
  point table over loopback. It checks the `point` items of both grade tools
  against the published output schema, their scale category and metadata, the
  "Wyn.I" result in `point_results` and not in `averages`, the point subject
  in final grades, and the point entries in grade notifications. It fails on
  API 1.6.4.
- An authorized live read of `grades`, `grades_window` and `final_grades` on
  the four owner logins, none of which has point grades, returned the same
  counts on API 1.7.0 as on 1.6.4, both from source and from the tagged wheel.
- `scripts/qualify_native.py --live --phase academic` on 2.4.0 with the
  published API 1.7.0: every grade tool passed on all four logins; 58 checks
  passed, 4 `get_completed_lessons` returned `VIEW_DISABLED` as before, and 6
  detail checks had no reference, two more than in 2.3.x because two logins'
  calendars currently list no detail entry. 102 requests.
- A live check on a point-grade account is pending.
- The catalog measures 126051 bytes for 31 default tools and
  139595 bytes for 35 tools.

## 2.3.1 tool definitions

2.3.1 rewrites tool and parameter descriptions; names, titles, annotations
and schemas are unchanged apart from descriptions and the alias pattern. A
comparison of the 2.3.0 and 2.3.1 all-feature catalogs with every
`description` removed found no difference other than the `account_alias`
pattern, whose new form accepted the same strings as the old one in Python
`re`, pydantic-core and ECMAScript over all 402234 strings of up to five
characters from an alphabet of printable, space, control and Unicode space
characters.

- `test_catalog_schema.py` also asserts a description on every input property
  in all three profiles; on 2.3.0 the default, minimal and all-feature
  profiles fail.
- pytest-timeout fails a test after 120 seconds; a parametrized test hanging
  inside `asyncio.run` failed with its parameter id. The slowest test takes
  about five seconds.
- The catalog measures 125729 bytes for 31 default tools and 139273 bytes for
  35 tools.

## 2.3.0 distribution qualification

2.3.0 adds the self-hosted HTTP transport, the container image, the MCP Bundle,
the MCP Registry listing and a single environment login; tools, inputs and
results are unchanged apart from titles and explicit destructive hints.

- `test_http_transport.py` owns HTTP: only one matching bearer token reaches
  MCP (missing, wrong, other scheme, non-ASCII and duplicate headers and
  `OPTIONS` get 401, lifespan always passes), token sources fail closed, the CLI
  refuses transport options outside serving and refuses HTTP without a token,
  WebSocket scopes are closed, and a real subprocess serves two logins over
  HTTP with grade reads from the synthetic wire, answers 421 for an unlisted
  Host, accepts a proxy's bare Host name under `NAME:*` and answers 413 above
  1 MiB. Blocking the lifespan in the middleware fails 25 cases; matching
  `NAME:*` only with a port fails the bare-name case.
- `test_config.py` owns the environment login, whose 8 cases fail without it,
  and the read-only mount error for a shared configuration file.
- `test_catalog_schema.py` asserts a title and explicit effect hints on every
  tool in the default, minimal and all-feature profiles; 3 profiles fail
  without the metadata. The catalog measures 120521 bytes for 31 default tools
  and 133772 bytes for 35 tools.
- `release_verification/test_registry_metadata.py` keeps `server.json`, the
  README marker and the Dockerfile label in step with the version.
- `verify_mcpb.py` starts the bundle through its own `mcp_config` command, and
  CI runs it on Linux, macOS and Windows. `verify_image.py` checks the image
  label, version, unprivileged user and contents, a stdio session from a
  read-only two-login file, and HTTP as the image user with a named volume:
  401 without the token, 421 for an unlisted Host, served with the token. CI
  builds the image from source and starts an arm64 build under QEMU; the
  release builds it from the verified wheel and verifies the pushed image.

Locally, on the candidate: 143 passed and 1 Windows-only skip from source, 137
passed and 1 skip from the isolated wheel built from the sdist, ruff, format,
strict mypy, Bandit, pre-commit, `mcp-publisher validate` and `mcpb validate`
passed. The README Docker Compose setup was followed with a locally built image:
401 without the token, 421 for an unlisted Host, both logins served, state kept
in `./data`.

On 2026-10-26 the candidate passed the installed MCP academic profile over
stdio: **56 reads** plus four identity checks with strict schema validation.
Four disabled completed-lesson views and four absent homework-detail references
were reported separately, using **104 requests and 3695812 response bytes**.
The live profile does not exercise HTTP; the transport serves the same runtime
and is verified offline and in the container checks.

## 2.2.2 security-update qualification

API 1.6.4 replaces the backtracking regular expression that decided whether a
message body is an XML wrapper with a linear scan (GHSA-c9qq-qqr2-hf23). The
library owns the regression tests; MCP source and tool catalog are unchanged.
Publishing moves to pypi-publish 1.14.3 and CI to setup-uv 10.3.2.

On 2026-10-26, after API 1.6.4 was published and its PyPI hashes matched the
lock, `pip-audit` of the full lock reported no known vulnerabilities, and the
candidate passed the source suite and the isolated wheel-from-sdist suite:
**89 passed, 1 Windows-only skip** in each. Ruff, format, strict mypy, Bandit,
native MIT archive inventory and installed CLI/stdio identity checks passed.
The installed MCP academic profile passed **56 reads** plus four identity
checks with strict schema validation. Four disabled completed-lesson views and
four absent homework-detail references were reported separately, using **104
requests and 3675065 response bytes**. The live profile does not open message
bodies; the fixed rendering is verified by the library's tests and a crafted
63 KB body rendered in 6 ms on the published 1.6.4.

## 2.2.1 attachment-namespace qualification

2.2.1 restores the optional `attachment_ref.archived` input that 2.2.0 removed.
It is the file's own namespace, which the API reads from the message detail's
`archive` field, so a current-mailbox message can carry archive-namespace files.
`test_attachment_stdio.py` owns the contract over real stdio:
- an omitted flag follows the message reference;
- an explicit flag selects the file's namespace;
- an archive message with `archived=false` fails before HTTP;
- a current message whose detail reports `archive: 1` downloads through the
  archive route, using the flag `get_message_content` returned.

Against the 2.2.0 implementation all three new cases fail. Against 2.1.3 only
the omitted-flag archive case fails. The catalog measures 119222 bytes for 31
default tools and 132354 bytes for 35 tools with all features. `pip-audit` of
the full lock reports no known vulnerabilities.

On 2026-10-25 the candidate passed the source suite and the isolated
wheel-from-sdist suite: **89 passed, 1 Windows-only skip** in each. Ruff,
format, strict mypy, Bandit, native MIT archive inventory and installed
CLI/stdio identity checks passed. The installed MCP academic profile passed
**56 reads** plus four identity checks with strict schema validation. Four
disabled completed-lesson views and four absent homework-detail references were
reported separately, using **104 requests and 3656389 response bytes**. The live
profile does not download attachments, so namespace selection is verified
offline only.

## 2.2.0 attachment-mailbox qualification

`download_attachment` drops its outer `attachment_ref.archived` input and takes
the mailbox from the message reference (#57, #58). `test_attachment_stdio.py`
owns the change over real stdio: current and archive references reach their own
attachment routes, and the retired field is rejected before any request. Both
cases fail against the 2.1.3 implementation. The catalog now measures 119149
bytes for 31 default tools and 132281 bytes for 35 tools with all features.
opentelemetry-api moves to 1.45.1; `pip-audit` of the full lock reports no
known vulnerabilities.

On 2026-10-25 the candidate passed the source suite and the isolated
wheel-from-sdist suite: **88 passed, 1 Windows-only skip** in each. Ruff,
format, strict mypy, Bandit, native MIT archive inventory and installed
CLI/stdio identity checks passed. The installed MCP academic profile, with the
newest permitted dependencies and strict schema validation for every successful
result, passed **56 reads** plus four identity checks. Four disabled
completed-lesson views and four absent homework-detail references were reported
separately. The shared budget recorded **104 requests and 3640413 response
bytes**. The live profile does not download attachments, so the mailbox
selection is verified offline only. No message bodies, sends, read-once
endpoints or production durable state were used.

## 2.1.3 security-update qualification

API 1.6.3 only raises its aiohttp floor. The MCP lock moves aiohttp, mcp,
mcp-types, multidict, PyJWT and yarl to releases without known advisories; MCP
source is unchanged. On mcp 2.3.0 the catalog still measures 119195 bytes for 31
default tools and 132327 bytes for 35 tools with all features.

On 2026-10-22, after API 1.6.3 was published and its PyPI hashes matched the
lock, `pip-audit` of the full lock reported no known vulnerabilities, and the
2.1.3 candidate passed the source suite and the isolated wheel-from-sdist suite:
**86 passed, 1 Windows-only skip** in each. Ruff, format, strict mypy, Bandit,
native MIT archive inventory and installed CLI/stdio identity checks passed.
API's installed release profile passed all 60 checks across four independent
authorized logins using 98 requests. The installed MCP academic profile, in an
environment resolved with the newest permitted dependencies (mcp 2.3.0, aiohttp
3.14.5, multidict 7.1.0, PyJWT 2.15.1), passed **58 reads** plus four identity
checks with strict schema validation for every successful result. Four disabled
completed-lesson views and two absent homework-detail references were reported
separately. The shared budget recorded **106 requests and 3640262 response
bytes**. No message bodies, sends, read-once endpoints or production durable
state were used.

## 2.1.2 school-layout qualification

API 1.6.2 accepts behaviour points in the grades `Zachowanie` row (validated and
left out of the results) and another school's completed-lesson layout. MCP code
changes are behaviour-preserving refactors, and the catalog still measures
119195 bytes for 31 default tools and 132327 bytes for 35 tools with all
features.

On 2026-10-19, after API 1.6.2 was published and its PyPI hashes matched the
lock, the 2.1.2 candidate passed the source suite and the isolated
wheel-from-sdist suite: **86 passed, 1 Windows-only skip** in each. Ruff,
format, strict mypy, Bandit, native MIT archive inventory and installed CLI/stdio
identity checks passed. API's installed release profile passed all 60 checks
across four independent authorized logins using 98 requests. The installed MCP
academic profile, with strict schema validation for every successful result,
passed **58 reads** plus four identity checks, including both grade tools on
each login. Four disabled completed-lesson views and two absent homework-detail
references were reported separately, so the new completed-lesson layout is
verified offline only. The shared budget recorded **106 requests and 3517193
response bytes**. No message bodies, sends, read-once endpoints or production
durable state were used.

## 2.1.1 school-read regression qualification

API 1.6.1 accepts both Sunday grade-date suffixes and preserves calendar closure
events without an ordinary-detail reference. MCP publishes clock fields with
an offset-optional ISO time pattern, preserving school wall time.

`test_academic_stdio.py` now validates all successful results against their
published output schemas. The strict `time` checker in `published_schema.py`
requires the RFC 3339 offset that strict hosts enforce, unlike jsonschema's
built-in time checker. This regression failed on the timetable before the fix.
An independent AJV 8.17.1 + ajv-formats 3.0.1 check of an actual synthetic stdio
timetable result passed with the corrected schema; restoring `format: time`
produced 14 format-validation errors on the same payload.

On 2026-10-12, paired local wheels passed the installed consumer suite:
**86 passed, 1 Windows-only skip**. API's installed release profile passed all
60 checks across four independent authorized logins using 98 requests. The MCP
academic profile, with strict schema validation for every successful result,
passed **60 reads**, including both grade tools, timetable and agenda on each
login. Four disabled completed-lesson views and four absent homework-detail
references were reported separately. The shared budget recorded **104 requests
and 3395782 response bytes**. No message bodies, sends, read-once endpoints or
production durable state were used. Disposable builds and environments were
removed. This is pre-publication evidence, not proof of deployment.

The updated catalog measures 119195 bytes for 31 default tools and 132327 bytes
for 35 tools with all features, within the existing 128/144 KiB budgets.

After API 1.6.1 was published and its PyPI hashes confirmed, the exact 2.1.1
candidate passed the source suite and isolated wheel-from-sdist suite again:
**86 passed, 1 Windows-only skip** in each. Ruff, format, strict mypy, Bandit,
native MIT archive inventory and installed CLI/stdio identity checks passed.

## 2.1 qualification

The 2.1 candidate pins API 1.6.0. `test_v21_stdio.py` owns the new consumer
contracts over real stdio and independently authored loopback responses:
formative paging/mirror IDs/date filtering/source drift; archive years and
achievements with empty/raw marks; class-free date/lesson ranges; modern
directory paging, unread counter projection, archive/filter continuation and
pre-I/O account/context/folder/query rejection. Existing suites retain ownership
of send, notification and attachment persistence/consent.

`test_message_stdio.py` covers the new legacy receipt class field, and
`test_native_stdio.py` covers redacted module-unavailable outcomes without a
second authentication. POSIX directory tests establish their starting modes
explicitly so they exercise the same boundary under a private umask.

Local Linux/Python 3.14.7 source qualification on 2026-10-09: **86 passed,
1 Windows-only skip**. Ruff/format, strict mypy, Bandit, lock consistency and
changed-file pre-commit checks pass. The MIT sdist rebuilds a wheel successfully.
Catalogs measure 119021 bytes/31 tools by default and 132153 bytes/35 tools with
all features, with typed outputs throughout. The isolated wheel rebuilt from
sdist also passes **86 tests, 1 Windows-only skip**, installed CLI/stdio identity,
schema and catalog-budget checks. Hosted
[CI run 37915990868](https://github.com/krzysztofbury/librus-mcp/actions/runs/37915990868)
passed on PR head `73b2c8e`: installed Linux/macOS 86 passed/1 skip each, Windows
65 passed/22 declared-profile skips, plus the Linux lint/test/build job.
PR #44 merged as `f569f19`; the annotated `v2.1.0` tag points to that commit.
The retained mutation report is migration-era evidence, not a refreshed 2.1 baseline.

### Published 2.1.0 artifacts

[Publish run 37916417945](https://github.com/krzysztofbury/librus-mcp/actions/runs/37916417945)
passed release identity, source, installed artifact and checksum verification,
then published through the protected `pypi` environment on 2026-10-09.
Downloaded PyPI bytes and PyPI metadata independently match the sealed workflow
artifact's SHA256 manifest:

- Wheel: `712d8b3fa1a07fbef317a963cd083388d9e21a966073e4af6633f779026438b1`.
- Sdist: `7aa1ffa47c2ab38ac422268fd446b888f892f911c3ab23b810613af4ea35652b`.

A fresh `uvx --no-config --isolated --python 3.14 --from librus-mcp==2.1.0
librus-mcp` installation with an empty disposable cache, outside the checkout,
reported version 2.1.0 and passed private synthetic config validation, stdio
initialization, all 31 default tool schemas, the catalog byte budget and offline
account listing. Metadata pins API 1.6.0. No live account was used for this
post-publication smoke check. All task-owned verification scratch was removed.

### Pre-publication live qualification

Authorized live qualification on 2026-10-09 used the locally built wheel and API
1.6.0 outside the checkout: **82 successful checks across four independent
logins**, using **126 requests and 1164769 response bytes**, within the shared
budget. Both grade tools returned formative data. School-year archives covered
populated and explicit empty results. Class-free-day and teacher-subject paging,
received/sent correspondent discovery and filters, current/archive inbox/outbox
summaries, unread filtering and available continuation paths passed. Counter
responses were typed successfully; the check does not establish additional
semantics for upstream counter names.

These are bounded samples, not exhaustive histories: one continuation at most
per returned cursor, and filters only when discovery supplied a reference.
Empty lists are recorded as empty, not populated coverage. No bodies, downloads,
sends, notification polling or production durable-state changes were exercised.
The qualifier's disabled feature profile was also checked with a synthetic config.
All task-owned build, installation and qualification scratch was removed.

For separately authorized ordinary live reads only:

```bash
uv run python scripts/qualify_native.py --live --phase v21 --config /private/path/config.json
```

This profile checks both grade tools, school-year history, class-free days,
modern discovery/counters, current/archive inbox/outbox lists, unread filtering,
one continuation per available cursor and one filter per available correspondent
list. The shared invocation budget is 160 requests, 360 seconds and 16 MiB.
Outputs contain slot numbers, tool/status/coverage and counts, never account
aliases, school text or references. Optional stores, sends and files are explicitly
disabled. No received/sent body open, download, notification poll, read-once
consumption or production-state migration is part of this profile. Authentication
still changes last-login baselines and grade scope selects the session view.

## Baseline and current test selection

The apix-era suite passed **569 tests** before dependency removal on 2026-10-05.
It is retained in `legacy_reference/tests/` as a GPL-scoped migration reference, not installed with the native
package and not executed by native CI. Many tests import apix/private wrappers or
assert deliberate 1.x contracts; they cannot truthfully validate 2.0 unchanged.
No apix dependency is retained to make that suite importable.

The active suite is `tests_native/`, selected by the pytest configuration and CI.
New tests exercise the public native application rather than legacy manager
mocks. The reduced initial test count alone was **not full 1.x safety parity**.
The owner map below identifies the retained native consumer invariants.
Historical wrapper mocks are not release requirements;
do not remove an independent safety proof without identifying its owner.

## Proof-owner map

| Legacy tests/concerns | Final owner and required evidence |
| --- | --- |
| CLI, config, credential files, feature gates | MCP; native tests cover selection, redaction, private-file limits, duplicate aliases, unavailable features, persistent context-key provisioning and explicit offline doctor/storage diagnostics. |
| MCP stdio/catalog/output models, tool errors, context budgets | MCP; native tests cover 31 default, 35 all-feature and 27 minimal tools, schema compilation, effects/projections, input/domain redaction, whole-result byte caps, pre-I/O cursor/reference guards and host-wide budget exhaustion. Installed profiles enforce 128/144 KiB catalog bounds. |
| Login cookies, retries, request limits, metadata caches, parser rules | API; use its existing public transport/parser proof. MCP retains real service-to-loopback tests for routing/traffic integration, not duplicate parsers. |
| Notification files, locks, pending spools, collision handling | API owns native transactions; MCP tests cover real old files -> reviewed bootstrap -> restart -> historical poll/ack, mirror/hash conflicts, malformed input, capacity rejection, manifest interruption and per-account quarantine. Raw checkpoint retention, archive round-trip and loss-consenting uncertainty resolution use public contracts. Supported platform profiles pass hosted acceptance; no automatic rollback is promised. |
| Send preview/confirmation, feature consent and UNKNOWN recovery | API owns durable claims/outcomes; MCP stdio tests cover both backends, exact token/payload binding, consent, native HTTP, restart recovery, accepted/rejected/unknown outcomes, cancellation/disconnect and no resubmission. Store-error projection is consumer-owned; claim/save transaction internals remain API-owned. |
| Attachment destination policy, consent and resources | API owns stream/publication; MCP stdio tests cover both backends, context binding, private publication, credential-free download, no implicit body open, incomplete-stream cleanup, inert snapshots/restart and post-publication snapshot fallback. Resource tests own capacity/expiry/no-follow checks. Windows native publication and POSIX snapshots pass their declared hosted profiles. |
| Wheel, sdist, installed console entry, stdio identity | MCP; verifier updated for native namespace/CLI/catalog and absence of apix. Include full installed public integration tests in local qualification. |
| Mutation safety evidence | Optional mutmut 3.7.0 targets MCP window cursors/pages and message bindings through actual stdio children: 62 killed/8 reviewed survivors. See `MUTATION_TESTING.md`; legacy campaigns are not native evidence. No score target or test-only production code. |

The original synthetic HTTP fixture in `tests_native/wire.py` was authored in this
repository from source-informed API requirements. It is not copied from API tests
or an upstream capture, and does not claim live compatibility. It exercises real
authentication and public service operations through stdio with four independent
logins representing the same student, one denied account, malformed HTML, native
grades/attendance and one shared concurrency budget. Modern fixtures also prove
native handoff, message paging/content consent and directory selection without
copied upstream captures or another project's tests. Result projection tests must
not substitute mocked API returns for that runtime path.
