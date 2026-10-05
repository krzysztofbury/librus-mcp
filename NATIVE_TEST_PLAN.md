# Native migration verification ownership

## Baseline and current test selection

The apix-era suite passed **569 tests** before dependency removal on 2026-10-05.
It is retained in `tests/` as a migration reference, not installed with the native
package and not executed by native CI. Many tests import apix/private wrappers or
assert deliberate 1.x contracts; they cannot truthfully validate 2.0 unchanged.
No apix dependency is retained to make that suite importable.

The active suite is `tests_native/`, selected by the pytest configuration and CI.
New tests exercise the public native application rather than legacy manager
mocks. The reduced initial test count is **not full 1.x safety parity**. Remaining
consumer invariants must be ported before feature integration and final release;
do not delete an old safety test until its owning replacement is identified.

## Proof-owner map

| Legacy tests/concerns | Final owner and required evidence |
| --- | --- |
| CLI, config, credential files, feature gates | MCP; native tests cover selection, redaction, private-file limits, duplicate aliases, unavailable features and explicit offline doctor/storage diagnostics. Key-file support remains deferred. |
| MCP stdio/catalog/output models, tool errors, context budgets | MCP; native tests cover the 22-tool default and 30-tool optional catalog, schema compilation, effects/projections, input/domain redaction, whole-result byte caps, pre-I/O cursor/reference guards and host-wide budget exhaustion. Final catalog review remains open. |
| Login cookies, retries, request limits, metadata caches, parser rules | API; use its existing public transport/parser proof. MCP retains real service-to-loopback tests for routing/traffic integration, not duplicate parsers. |
| Notification files, locks, pending spools, collision handling | API owns native transactions; MCP tests now cover real old files -> reviewed bootstrap -> restart -> historical poll/ack, mirror conflicts, malformed input and per-account quarantine. Raw checkpoint retention and archive round-trip are exercised through public contracts. Broader failure/platform/rollback qualification remains W5 work. |
| Send preview/confirmation, feature consent and UNKNOWN recovery | API owns durable claims/outcomes; MCP stdio tests cover exact token/payload binding, consent, native HTTP, restart recovery, accepted/unknown outcomes and no resubmission. Legacy/cancellation/disconnect qualification remains open. |
| Attachment destination policy, consent and resources | API owns stream/publication; MCP stdio tests cover context binding, private publication, credential-free download, no implicit body open, incomplete-stream cleanup, inert snapshots/restart. Resource tests own capacity/expiry/no-follow checks. Actual Windows/macOS consumer and legacy backend qualification remain open. |
| Wheel, sdist, installed console entry, stdio identity | MCP; verifier updated for native namespace/CLI/catalog and absence of apix. Include full installed public integration tests in local qualification. |
| Mutation safety evidence | Re-scope to MCP-owned policy branches after integration; legacy mutation configurations are not native evidence. No score target or test-only production code. |

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

## Required future qualification

- Broaden installed stdio integration to all enabled families and real persistence.
- Record equivalent old/new representative workloads before claiming performance
  gains, including warm/cold request counts, latency distribution, peak memory,
  rate/burst/queue saturation, concurrent tools and cancellation.
- Exercise Linux, macOS and Windows on actual respective CI hosts. Local Linux
  success and upstream Windows CI are not consumer Windows qualification.
- Qualify public API #22-25 at their released contracts; keep #26-27 deferred.
- Audit provenance/dependency licenses before switching artifacts to MIT.
- Keep ordinary CI offline. Release-time live checks need separate scoped approval;
  no routine read-once events, message-open mark-read operations or sends.
- Before calling a live family unavailable or treating an empty result as a native
  regression, compare the published 1.x MCP using the same account, date range,
  folder and bounds. Distinguish account-specific empty data, unsupported backend
  operations, features absent from the configured catalog and intentionally
  unexercised effects. Never invent a reference or send a message to create test data.
