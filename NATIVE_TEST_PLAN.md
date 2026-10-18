# Native migration verification ownership

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

