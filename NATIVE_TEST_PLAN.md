# Native migration verification ownership

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
The owner map and subsequent qualification below identify the retained native
consumer invariants. Historical wrapper mocks are not release requirements;
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

## Current slice evidence

Local evidence for the initial slice on 2026-10-05:

- 24 native tests passed both against the development installation and an isolated
  wheel installation outside the checkout, with no apix package installed.
- Ruff/format, strict mypy and Bandit passed on the native runtime.
- Built the wheel from its sdist; checked both omit old implementation/tests.
  Installed CLI version/config checks, stdio identity and local account listing passed.
- Catalog measurement: 5 typed tools, 14851 serialized bytes.
- API prerequisite tests: 46 passed; 25 real-Windows tests skipped on Linux.
  Upstream hosted CI succeeded at `57db02d`; MCP macOS/Windows CI is still pending.
- This initial baseline involved no live requests, production-state changes,
  performance claims or publication. It predates the broader qualification stage.

Subsequent read integration adds a schema-compilation regression for a
nonportable alias regex, civil-date validation, changed-query/context/source
cursor rejection, explicit received-body consent and modern mailbox/directory
runtime proof. The explicit live script is opt-in and keeps ordinary CI offline.
It reports empty/unexercised/unsupported branches rather than presenting these
as populated-response verification. Credentialed evidence and school data must
not be stored in this public repository.

Expanded local Linux evidence on 2026-10-05:

- 30 native tests passed against both the development installation and an
  isolated wheel installation outside the checkout, with no apix installed.
- Native Ruff/format, mypy, Bandit and lock checks passed.
- Catalog measurement: 22 typed tools, 92748 serialized bytes, below 96 KiB.
- The wheel built from its sdist passed installed CLI, identity, account listing,
  catalog-schema compilation and byte-budget checks.
- The installed verifier now has `--consumer-tests` to run the copied offline
  suite against the wheel; the compatibility matrix uses this option. Hosted
  macOS/Windows results remain pending until those jobs actually run.

Durable integration evidence on 2026-10-05:

- 51 native tests passed against the development installation and an isolated
  wheel built from its sdist, outside the checkout, without apix installed.
- Both installed feature profiles passed stdio identity, schema compilation and
  size checks. The default catalog remains 22 tools/92748 bytes; the supported
  optional catalog is 30 tools/126491 bytes, below 128 KiB.
- New consumer proofs include native send claims across three processes,
  accepted/unknown dispatch outcomes, no replay, private attachment publication,
  resource snapshots/expiry/capacity, durable notification replay/ack, retained
  malformed read-once checkpoints and old-state quarantine.
- POSIX migration tests cover safe and hashed/mirror names, single/batch spools,
  corrupt/shared/symlink/invalid-Unicode sources, mapping/context/fingerprint/approval guards,
  original-file retention, public bootstrap, historical replay after restart and
  exclusive archive export restored through the public API into an empty store.
- Offline doctor/storage diagnostics exercise disposable native stores without
  opening existing history. These are Linux results, not macOS/Windows evidence.
- Ruff/format, strict mypy, Bandit, lock consistency and diff checks passed.
- Pre-commit hooks passed for every changed/new file. An additional whole-repository
  secret scan flagged existing unmodified synthetic fixtures and public action SHA
  pins; those baseline false positives were not suppressed by changing unrelated
  files. Review the historical scan baseline before final release.

## Expanded native qualification

The post-review suite passes **73 tests, 1 Windows-only skip** on Linux, including
an isolated wheel rebuilt from its audited MIT sdist. The installed verifier
also exercises the actual CLI and both feature catalogs outside the checkout.

New independent consumer evidence:

- Remaining academic families through the public API and real stdio, including
  unknown attendance ratios, school wall times, bound details and lesson cursors.
- Both explicit messaging backends across paging, consent, directory/legacy
  group choices, durable sends, downloads and notification replay/ack.
- Accepted, rejected, unrecognized and disconnected send outcomes; cancellation
  after observed dispatch; offline restart recovery without consumer resubmission.
- Public store errors before/after execution are closed `STORAGE` results without
  consumer retry. Native claim/save transaction internals remain API-owned proof.
- Snapshot failure after native publication returns the complete local file,
  not an apparent failed download. The regression failed before the adapter fix.
- Actual historical short-hash alias collision, over-capacity source retention,
  pre-/post-bootstrap manifest interruption, archive export and empty/populated
  target recovery. Old files remain unchanged.
- Lost consume response remains `CHECKPOINT`-quarantined after restart. Operator
  export and separately loss-consenting uncertainty resolution stay offline.
- Four-login mixed cold/warm workloads at 3 and 100 mailbox records, concurrent
  academic calls, independent contexts, one login per account, shared concurrency
  and complete response-byte bounds. This is safety/load qualification, not a
  speedup or old-versus-new performance benchmark.

Hosted macOS passed the expanded pre-license suite at `acc10a0` in run
[37364751785](https://github.com/krzysztofbury/librus-mcp/actions/runs/37364751785).
That run's Linux/Windows jobs never acquired hosted runners and are not test
evidence. The final source/sdist matrix is required after the coordinated MIT
cutover. Windows's positive/negative credential ACL case must execute there.

The final MIT candidate at `57d56ce` passed hosted Linux installed-wheel-from-sdist
acceptance and the lint/test/build job in run
[37367482358](https://github.com/krzysztofbury/librus-mcp/actions/runs/37367482358).
macOS again failed to acquire a hosted runner. Windows ran and stopped at an
artifact-verifier bug before consumer tests: its CRLF license header was rejected
by an LF-only prefix check. The fix accepts only the exact MIT header followed by
LF or CRLF; inventory and license metadata checks remain unchanged. A disposable
CRLF checkout reproduced the pre-fix failure on real artifacts, then passed sdist
verification, rebuilt-wheel CLI/stdio and all 73 consumer tests after the fix.
This reproduction is Linux evidence, not actual Windows qualification.

At `bdbc664`, hosted macOS passed the full MIT installed-wheel-from-sdist suite
in run [37371176343](https://github.com/krzysztofbury/librus-mcp/actions/runs/37371176343).
Windows passed the artifact checks and reached the installed CLI, exposing a
wrong pywin32 constant namespace: `FILE_FLAG_OPEN_REPARSE_POINT` must come from
`win32file`, not `win32con`. Both parent and file opens retain the same no-follow
flag after correction. Windows's full consumer suite still requires actual host
execution; the Linux/lint jobs in that run did not acquire runners.

The 1.x source/tests were preserved under `legacy_reference/`, not deleted or
imported into native tests. Reusable parser/storage/scheduler invariants are owned
by the API, as mapped above; obsolete mocks/return shapes do not count as 2.0 proof.
Cosmic Ray's old configurations are scoped with those historical references.

## Final hosted platform qualification

Run [37372839458](https://github.com/krzysztofbury/librus-mcp/actions/runs/37372839458)
completed successfully for remote PR head
`bc10abeea473a1492739bab76e03515953f9fbf7`. Runner acquisition failures were retried;
only actual executed jobs count as qualification.

| Hosted profile | Installed consumer result | Additional acceptance |
| --- | --- | --- |
| Linux | 73 passed, 1 Windows-only skip | Audited MIT sdist, rebuilt wheel, private CLI config, stdio identity and both schema/catalog budgets |
| macOS | 73 passed, 1 Windows-only skip | Same installed artifact/CLI/stdio/catalog checks; POSIX migration/recovery and resources |
| Windows | 56 passed, 18 skipped | Same artifact/CLI/stdio/catalog checks; real NTFS private/shared credential ACL and hardlink guards, native durable stores and local file publication |

Windows skips retain the declared POSIX-only migration/operator recovery,
credential mode/FIFO and no-follow snapshot boundaries. No skips are treated as
evidence for unavailable Windows features. The lint/test/build job also passed.
Both messaging backends and the four-login mixed workload are exercised by the
applicable installed suite, not just startup or a low-load live window.

The remaining release step is separately authorized merge/version/tag/publication
and fresh remote installation verification. This qualification does not authorize
production migration or claim live send, received-body, download or read-once
compatibility. The current candidate remains `2.0.0.dev1` and PR #39 remains draft.

## Checklist and mutation reconciliation, 2026-10-06

All 18 original major-release TODO items now record their implemented outcomes
and deliberate contract/platform differences in `TODO.md` and plan section 7.
Publication remains W8, not implied by checked implementation items.

The focused mutmut 3 campaign ran offline through real instrumented stdio
children. It selected 70 mutants: 62 killed, 8 individually reviewed survivors,
no selected no-test/timeout/suspicious outcomes. Existing owner tests were
strengthened for consent-enabled independent account/context rejection, exact
end-offset rejection and public truncation/reason fields. No production code
was changed for instrumentation. See [MUTATION_TESTING.md](MUTATION_TESTING.md)
and `mutation/native-baseline.json` for scope, hashes and survivor diffs.
The earlier hosted matrix remains the runtime qualification baseline; this
follow-up's new test/tooling checks must be recorded separately.

Local Linux verification for the follow-up passed the 73-test consumer suite
(one Windows-only skip), strict mypy, Ruff/format, Bandit and lock consistency.
Its audited MIT sdist was rebuilt into a wheel and installed outside the checkout;
CLI, stdio identity, both catalogs and all 73 consumer tests passed there without
mutation dependencies installed. The final focused campaign rechecked the stored
baseline with the consent-enabled backend guard and again produced 62 killed/8
reviewed survivors. New hosted results must be checked against the pushed PR head;
the earlier green run is not evidence for a new commit's test/build inputs.

## Ongoing and release-time requirements

- Requalify applicable installed profiles when runtime/dependency/build behavior changes.
- Record equivalent old/new representative workloads before claiming performance
  gains, including warm/cold request counts, latency distribution, peak memory,
  rate/burst/queue saturation, concurrent tools and cancellation.
- API #22-25 are qualified through their released consumer contracts; keep #26-27 deferred.
- Keep [LICENSE_REVIEW.md](LICENSE_REVIEW.md) current as dependencies/artifacts change.
- Keep ordinary CI offline. Release-time live checks need separate scoped approval;
  no routine read-once events, message-open mark-read operations or sends.
- Before calling a live family unavailable or treating an empty result as a native
  regression, compare the published 1.x MCP using the same account, date range,
  folder and bounds. Distinguish account-specific empty data, unsupported backend
  operations, features absent from the configured catalog and intentionally
  unexercised effects. Never invent a reference or send a message to create test data.

## Release review and setup automation, 2026-10-06

Version `2.0.0` pins published `librus-python-api==1.0.2` (wheel SHA256
`c589d525913d8cf3a5a6e18c9cec182f5ee2dd5b788b475ab2774987990e0bb6`). API 1.0.0
failed `get_subject_frequency` with `LIMIT` on a cold session for students with
about 15 subjects; 1.0.1 uses 12 requests including login. 1.0.2 raises the
shared request policy to 10 requests/second, burst 20 and four in flight.

- Setup needs no operator steps: missing context keys are created once in
  `state_dir/context.key`, the user's own shared configuration file and
  directories are restricted in place on POSIX, the 1.x `secrets.json` default
  and `behaviour_notes` are accepted, and 1.x notification files are adopted on
  the first poll (pending agenda events imported, originals archived).
- `get_grades`/`get_attendance` page by `limit`/`cursor`; text content is compact
  JSON; a failed post-send outcome read returns the completed send with
  `durable: null`; acknowledgement accepts the batch context object verbatim.
- Notifications and attachments are on by default (as in 1.x); sending stays
  opt-in. Tests and child servers run with an isolated home directory.
- Offline: 83 passed, 1 Windows-only skip; Ruff/format, strict mypy, Bandit and
  lock checks pass. Published schemas omit generated `title` annotations.
  Catalogs (measure_tools): default 26 tools/92713 bytes, all features 30
  tools/105452 bytes; both budgets are 128 KiB. Mutation campaign unchanged:
  62 killed, the same 8 reviewed survivors.
- Read-only live benchmark against MCP 1.7.0 on the same four logins (cold and
  warm overviews, statistics, two notification checks without agenda, parallel
  grades, sent-message opens): 1.7.0 made 264 requests in 27.3 s, peaking at 53
  requests/second, with 2 failed sent-message opens; 2.0.0 on API 1.0.2 made 182
  requests in 25.4 s, peaking at 14 requests/second, with no failures. Its tool
  list is 93 KB against 37 KB for 1.7.0; both publish output schemas, but the
  native types carry bound references, availability, observations and cursors.
- Read-only live rehearsal on four independent logins, using copies of a real 1.x
  configuration and state directory: startup restricted the copied 0644 config
  and 0755 download directory, ignored behaviour notes, created the key and
  adopted all four accounts' 1.x files; first polls (all categories except agenda)
  returned 12/12/20/20 items, acknowledged, and second polls returned none. No
  sends, read-once consumption, received-body opens or downloads were made.
