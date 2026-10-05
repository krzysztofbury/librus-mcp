# MCP 2.0 native API migration plan

Status: implementation started on 2026-10-05. The original architecture proposal
is retained below; current slice and deviations are documented in
[MIGRATION_2_0.md](MIGRATION_2_0.md). Final qualification and MIT cutover remain pending.

## Implementation progress

- API issues #22-25 are closed. Remote main is
  `57db02df28f3ce02bed9999a08083759d53c4edb`; stable API `1.0.0` is on PyPI.
  Modern notifications, neutral external bootstrap, offline recovery status and
  pending lookup are public. Windows NTFS disk support is now qualified upstream;
  unsupported Windows filesystems still fail closed. Consumer Windows tests remain required.
- Native package/console entry, explicit config/key provisioning and shared async
   service lifespan are implemented in `2.0.0.dev1`, with 22 default tools and 30
   with supported optional features. Ordinary read families, presentation/native cursors,
  bound detail references and explicit received-open consent are integrated.
  Apix is absent from runtime/dev dependencies and lockfile. Old source/tests are
  excluded from native artifacts, retained only for future proof/provenance mapping.
- During this incomplete slice, notifications/files/sends default off but can be
  explicitly enabled. Behaviour notes remain unavailable and reject enablement.
  A context key can be provided in private config/environment rather than a new
  key-file workflow. Doctor/storage probes, durable sends/outcomes, file publication/
  resources and notification poll/status/ack are integrated. POSIX old-state
  inventory/bootstrap, private manifests and native archive export are implemented;
  remaining migration/platform/safety qualification is pending. A separate
  explicit-live qualification script uses bounded native
  budgets and emits redacted coverage; it does not grant routine CI live access.
- #26-27 stay parked; no live access or publication is authorized by implementation.

## 1. Baseline and release objective

Remote evidence checked before branching:

| Component | Reviewed revision and state |
| --- | --- |
| MCP `main` | `0aaf658c657197817a7c8cae35d39f05484403fd`, released as 1.7.0, GPL-3.0-only, Python 3.14+, `librus-apix==1.5.2` |
| API `main` | `01b32e0dd2407809cf89aec32b1e49b32b2a3363`, MIT, Python 3.13+, native async service and optional disk workflows |
| API PyPI | `1.0.0rc1` published on 2026-10-05; library-only candidate, not completed MCP integration |
| MCP work branch | `feat/2.0.0-native-api`, created directly from the reviewed MCP main |
| Earlier experiment | `feat/native-identity-adapter` has three commits beyond main, ending at `1b400cf`; identity/final-grade experiments are not part of the baseline |

PyPI reports wheel SHA-256
`c879dcb4fda13314254e0c0d012c9a2981e87f8b7a431247df9c3990a4fbe893`
and sdist SHA-256
`7ecbefdba84714dc95080665d4019adbc40c497475856e897d24a51b6433be13`.
This planning review checked registry metadata, not a fresh artifact installation.
Some API README/TODO publication checkboxes still say pending; remote publication
evidence takes precedence over that prose.

Deliver MCP 2.0 directly on native library contracts, with MIT-licensed release
artifacts after the provenance gate. No intermediate 1.x compatibility adapter,
fallback to apix, or preservation of legacy wire shapes is required. Preserve
account isolation, bounded traffic, consent, uncertain-send protection and
recoverability of already-consumed events.

The existing GPL releases, tags and artifacts retain their licenses. Historical
MIT releases before the GPL adoption are likewise not rewritten. Implementation
on this branch initially remained under its GPL license until the coordinated license
cutover; changing the dependency alone does not change source ownership.

## 2. Target ownership: a thin MCP application

| Responsibility | Final owner |
| --- | --- |
| Login/session/cookie isolation, authentication recovery and cooldown | API |
| Shared rate, burst, concurrency, queue, request, byte and deadline budgets | API service |
| Fetching, parsing, typed domain results, upstream pagination, metadata caches | API |
| Message backend selection mechanics and reference validation | API; MCP selects an explicit configured backend |
| Notification polling/diff, IDs, persistence, checkpoint/replay and acknowledgement | API workflow/store |
| Send preparation, exact payload binding, confirmation expiry, durable claims and outcomes | API persistence/send workflow |
| Attachment resolution, streaming, safe filenames and atomic publication | API streams and optional file layer |
| Credential/config sources, account aliases, context-key provisioning and selected directories | MCP |
| Feature registration, human-facing preview/consent and MCP effects | MCP |
| Wire DTOs, JSON errors, projections, response/context budgets and resource hosting | MCP |
| Old MCP file interpretation, explicit upgrade/rollback CLI and mapping report | MCP adapter, using public API import/export primitives |
| Selecting accounts and combining observations into a summary | Calling application/assistant; no library summary endpoint |

Proposed package layout, to be created during implementation:

```text
src/librus_mcp/
  cli.py             # CLI routing, config checks, doctor and explicit migration
  config.py          # Validated application configuration and secret/path policy
  runtime.py         # One service plus explicitly opened stores; joined shutdown
  server.py          # MCP registration and lifespan
  tools/             # Small domain-family handlers calling public API operations
  schemas/           # MCP request/response models and explicit native projections
  errors.py          # Closed domain-to-MCP error mapping
  resources.py       # Bounded local attachment resource delivery, if enabled
  migration.py       # Old MCP format adapter, never runtime scraping or SQL
```

Do not retain `LibrusManager` as a second session/retry/cache layer. Remove
`librus_optimizations.py`, `scraping.py`, `response_limits.py` and the runtime
JSON notification store only when their replacing boundary passes integration
proof. The retained migration code has no apix import and no normal polling path.
MCP must not import API private helpers, SQL tables, raw routes or parser modules.

### Lifecycle and traffic

- Construct one `LibrusService` for the server process in its async lifespan,
  and reuse it for every configured login and every tool call. No login during
  import, configuration validation, tool listing or server initialization.
- Four configured logins remain four independent security contexts even where
  parent/student data overlap. Never deduplicate sessions or caches by child.
- Open only stores needed by enabled features. Shutdown joins tool work and
  closes stores and the service in an order that permits durable final saves;
  verify cancellation during active sends, notification checkpoints and downloads.
- Supply API limits from validated application settings; do not expose arbitrary
  rate increases as tool arguments. Start qualification with documented API
  defaults: 5 requests/s, burst 10, 2 active globally, 1 per account, 32 queued
  globally and 8 per account. These are not a Librus-approved quota.
- One ordinary tool budget initially uses the API's 32 attempts, 120 seconds
  and 4 MiB total response bytes. Downloads need explicit larger byte budgets
  including authentication overhead, within a 50 MiB file ceiling. Measure and
  document any policy override before adopting it.
- Shared service limits cover concurrent calls across aliases. Separate stdio
  processes have separate traffic budgets; state locks are not a distributed
  rate limiter. Recommend one active account deployment and document this limit.
- No retry decorator, parallel apix backend, automatic backend fallback or
  second task pool in MCP. Session-changing reads retain native no-replay policy.

## 3. Request and response contract

These are proposed MCP 2.0 choices, to be frozen in `MCP_CONTRACT.md` with schema
examples before endpoint implementation. Native Python objects remain library
contracts; MCP JSON is explicitly projected and validated.

### Common rules

1. Rename `student_alias` to `account_alias`, and `list_students` to
   `list_accounts`. Aliases identify independent logins, not upstream people.
2. Use `scope` for grade/attendance filtering, mapping to native `view` enums.
   Keep exact `all`, `week`, `last_login` semantics. Document authentication's
   effect on last-login windows; do not invent historical catch-up guarantees.
3. Use strict integer year/month, ISO civil `date_from`/`date_to` and a Monday
   date for timetable selection. Homework defaults to today through today + 14
   days in Europe/Warsaw; only both supplied or both omitted. Other optional
   boundaries follow the native per-operation contract.
4. Replace URL-like arguments with discriminated reference DTOs. Preserve
   account, folder, source/backend, kind and native identifiers. Add the current
   keyed account-context identifier at the MCP reference/cursor boundary so an
   old reference cannot be used after reassigning an alias to another login.
   Validate binding before invoking the API. These values are not consent tokens.
5. Use arrays of records, never dictionaries keyed by subject/person display
   name. Preserve duplicate labels; do not fabricate IDs absent from a source.
6. Use native attendance `ratio` in 0..1 or null, plus attended/total/excluded/
   unknown counts. Keep grade symbols and school averages as reported strings.
7. Preserve null, unavailable, disabled and malformed distinctions. Civil school
   times remain wall times with their timezone label, not invented UTC instants.
8. Expose normalized detail records with `key`, `raw_label`, `value` and notes.
   Unknown keys remain null; raw text is inert data, never a dynamic schema.

### Envelopes and continuation

- Collection success: `items`, `pagination`, `observation`, plus explicitly
  typed family metadata where needed (grade summaries, semester information).
  Pagination has `next_cursor`, `truncated`, `reason`, `pages_fetched` where
  meaningful, and `consistency="best_effort"`. Observation retains native source
  and observed time; it never claims a transactional snapshot.
- Single-object success: `data` and `observation`. Local-only results such as
  account aliases have no fabricated upstream timestamp or page cursor.
- Grades can expose discriminated numeric/descriptive records plus separate
  school-summary arrays. Window output omits undated summaries explicitly.
- Messages and completed lessons use native bounded collection operations:
  default limit 100, maximum 256, default max_pages 2, maximum 8. Preserve the
  full native cursor in a versioned, bounded MCP DTO, including fingerprints and
  seen-ID history. Do not expose a misleading cross-backend page index.
- Grade/attendance window offset/limit is presentation paging only. Bind a
  presentation cursor to query/context and a deterministic source fingerprint;
  reject changed source data rather than imply a frozen snapshot. This is one
  small shared MCP projection helper, not another upstream traversal engine.
- Remove `all_pages` and the redundant completed-lesson page tool. No eager
  fetch-all helper or internally exhausted upstream cursor to emulate 1.x lists.
- Measure the complete serialized MCP result, including text and structured
  content. Proposed hard tool-result cap: 512 KiB, subject to worst-case fixture
  qualification; keep the existing 48/64 KiB catalog budgets until a measured
  redesign justifies another value. Input cursor/reference bytes are bounded too.
- No silent text/item slicing. Pure read overflow returns a stable limit error
  with narrower-query guidance. Pending notification payloads remain durable and
  unacknowledged if serialization fails; choose store batch limits that fit the
  wire envelope before enabling consumption. Write receipts must stay small and
  must not be lost because a preview/body was needlessly echoed after dispatch.

### Errors and effects

Map every native `ErrorKind` explicitly, retaining distinct rejected credentials,
account action, expiry, denial, disabled view, unsupported capability, throttling,
maintenance, connection, timeout, limit, parse, stale cursor, checkpoint, storage,
closed and unknown-delivery outcomes. Add MCP-specific `CONFIG_INVALID`,
`CONFIRMATION_REQUIRED` and input/binding errors. Do not collapse all failures
into `AUTH_FAILED` or attach raw causes, inputs, HTML or tokens.

Use `isError=true` plus a small documented JSON error body with a stable code and
safe action guidance. Error results are separately tested from success output
schemas. UNKNOWN sends carry an outcome lookup reference and no retry advice;
ACCEPTED means upstream acceptance, not confirmed delivery or recipient reading.
Cancellation is joined and propagated, not translated into an empty success.

Annotations follow the API operation registry, not the HTTP verb or old MCP
annotations. Grade/attendance view selection, timetable selection and mailbox
selection can change session state. Received message opens may mark read and
require `allow_mark_read=true`; conservative non-read-only annotations also cover
handlers whose effects depend on folder. Acknowledgement and confirmation are
local writes. Only truly local tools have `open_world_hint=false`.

### Tool-by-tool disposition

| Existing 1.7 tool | Proposed 2.0 tool/path | API operation or owner |
| --- | --- | --- |
| `list_students` | `list_accounts` with alias records | MCP config |
| `get_student_information` | Retain name; native profile DTO | `student_information` |
| `get_grades` | Retain, scope and native records/summaries | `grades` |
| `get_grades_window` | Retain, scope/date bounds and presentation cursor | `grades_window` |
| `get_final_grades` | Retain, explicit availability | `final_grades` |
| `get_attendance` | Retain, scope and record arrays | `attendance` |
| `get_attendance_window` | Retain, scope/date bounds and presentation cursor | `attendance_window` |
| `get_attendance_detail` | `attendance_id` input | `attendance_detail` |
| `get_attendance_frequency` | Native ratio/count records | `attendance_frequency` |
| `get_subject_frequency` | `date_from`/`date_to`, ratio/count records | `subject_frequency` |
| `get_homework` | Native records and bounded multi-month range | `homework_range` |
| `get_homework_detail` | `homework_ref` input | `homework_detail` |
| `get_schedule` | Rename `get_agenda`, integer calendar | `agenda` |
| `get_schedule_detail` | Rename `get_agenda_detail`, `event_ref` | `agenda_detail` |
| `get_timetable` | Retain nested day/period/group records | `timetable` |
| `get_announcements` | Native content/date/reference records | `announcements` |
| `get_completed_lessons` | Bounded native cursor collection | `completed_lessons` |
| `get_completed_lessons_page` | Remove; use the collection cursor | Same native operation |
| `get_messages` | Explicit configured backend, native cursor | `messages` / `modern_messages` |
| `get_message_content` | `message_ref`, explicit received-open consent | `message_content` / `modern_message_content` |
| `get_message_attachments` | Remove; content already returns metadata with consent | Native content result |
| `download_attachment` | `attachment_ref`, bounded save and metadata/resource link | Native stream + `files.publish_attachment` |
| `get_recipient_groups` | `get_recipient_types`, preserve backend/hierarchy | `recipient_groups` / `modern_recipient_types` |
| `get_recipients` | Typed type/selection reference | `recipients` / `modern_recipients`; add `get_recipient_choices` for legacy hierarchy |
| `send_message` | Split `preview_message` and `send_message` | Native prepare + `PersistenceStore.preview_send` / `execute_send` |
| `get_new_notifications` | `poll_notifications`, explicit categories/consume permission | `NotificationWorkflow.poll` |
| `get_recent_schedule_events` | Remove; explicit agenda-category poll | Same workflow and durable checkpoint |
| `get_behaviour_notes` | Unavailable until API evidence gate closes; no 1.x parser fallback | API issue #26 |

Add `acknowledge_notifications` and `get_notification_status` for two-phase
delivery/recovery, and gated `get_send_outcome` / `get_send_history` for uncertain
sends. These remain bounded public store calls. Destructive retention/pruning
and acceptance of possible event loss belong in explicit operator CLI commands,
not automatic agent recovery. Freeze the resulting catalog size after feature
profiles and schemas are measured, not by preserving the old 24/28 tool count.

## 4. Configuration and platform choices

- Keep Python 3.14 as the initial MCP minimum. API support for 3.13 does not
  automatically justify widening MCP's tested Python contract.
- Proposed credential precedence: CLI `--config`, `LIBRUS_CONFIG`, explicit
  `LIBRUS_ACCOUNTS`, then `$XDG_CONFIG_HOME/librus-mcp/config.json` (default
  `~/.config/librus-mcp/config.json`). Conflicting explicit selectors should fail
  with redacted guidance rather than silently route another login. Environment
  feature/path overrides remain explicit and validated. No cwd/project discovery.
- Keep current default state/download roots initially, with separate versioned
  native subdirectories, to make old-state detection and upgrade instructions
  unambiguous. Never auto-open old files with the native store.
- Add a caller-owned persistent 32-byte context key. Prefer an explicit private
  key file, with an operator initialization command and no replacement on startup
  if it is missing while state exists. Share/back up the key with cooperating
  processes. Never derive it from credentials or generate a new key per tool.
- Config supports expected owner/student IDs and one explicit messaging backend
  per account. Proposed default for new 2.0 installations: modern; legacy is an
  explicit compatibility choice. Upgrade requires a recorded backend selection
  and notification-state mapping, not probing both backends automatically.
- Notifications and attachments can remain default-on only on qualified platform
  paths. Sending remains default-off. Enabling unsupported notes fails explicitly.
- Preserve Linux/macOS/Windows as the planning target until the owner decides
  otherwise. API #25 blocks Windows disk-feature parity. A POSIX-only 2.0 is an
  explicit scope decision with revised docs/CI, not an incidental dependency effect.
- `--version` and `--check-config` remain offline; `doctor` uses disposable local
  storage, not production checkpoint mutation. `doctor --live` uses bounded native
  profile reads only and does not imply send/read-once authorization.

## 5. Durable workflows and migration

### Notifications

`poll_notifications` returns a durable receipt, requested categories, first-run
state, typed items and `has_more_schedule`. Normal defaults exclude agenda
consumption; selecting agenda requires explicit consume consent. An outstanding
batch is replayed until `acknowledge_notifications(receipt)` is called after the
caller has received/processed it. Do not acknowledge inside the handler before
MCP transport delivery. A lost acknowledgement can replay data: at-least-once.

API #22 supplies modern mailbox polling. API #24 supplies offline recovery
discovery after a lost response/restart, so the consumer never decodes internal
archive bytes just to find the pending category tuple or receipt. Preserve an
oversized or malformed checkpoint; neither parse nor display failure authorizes
another consume. First-run data is a bounded observation, not full account history.

### Sending

`preview_message` validates native recipient references and prepares a send
without HTTP, then persists its exact payload/backend/context binding. MCP returns
the preview and expiring token; the human-facing caller approves it. `send_message`
reconstructs the exact immutable input and redeems the native single-use durable
claim. No MCP token dictionary, hashing algorithm, send retry or post-send lookup.

The token establishes payload binding, not proof that a human approved it; the
same agent can hold both calls. Describe this limitation accurately. Retain
CLAIMED/UNKNOWN history through restart and failed final saves. Outcome/history
tools permit inspection, never automatic resubmission or inferred reconciliation.

### Attachments

Call native publication into the configured private directory. Return basename,
size_bytes, content type, digest and an opaque MCP resource link if implemented.
Never expose signed remote URLs or take arbitrary filesystem paths from tool input.
Resource reads resolve only files created by this runtime, with bounded registry
entries, expiry, no-follow reads, configured byte limits and no network refetch.
Binary bodies stay out of normal tool results; unsupported host resource behavior
has a documented server-local file fallback. Resource hosting is MCP-owned.

Adopt and document the native commit-point semantics: incomplete downloads do not
publish; cancellation or filesystem error during atomic publication may leave a
complete file, but joined workers cannot continue later. This differs from an
absolute promise that cancellation leaves no final file. Do not add a second
MCP publication implementation to hide that difference.

### Existing MCP state

1. Stop all 1.x writers before upgrade; old and native stores cannot coordinate
   transactions merely by using different lock files. Require a maintenance
   window, explicit source/target paths and an account-to-login binding review.
2. Add an offline `migrate-state --dry-run` inventory with strict private-file,
   size, schema, digest and collision validation. Old safe aliases, full-hash
   names, short-hash mirrors and single/batch spools all need explicit handling.
3. Old baselines contain ID strings, not native domain records; old schedule
   spools contain parsed three-field events, not raw native HTTP envelopes.
   Do not manufacture identity/observation provenance or edit native SQLite.
4. Map only identities proven equivalent. Schedule hashes use the same three
   visible fields, but every category needs independent mapping evidence.
   Unmappable IDs or conflicting mirror files block that context and produce an
   actionable report; never silently reset history. API #23 is the required
   neutral bootstrap/staging boundary for already-consumed historical records.
5. Import into an empty native context in one supported bounded operation;
   preserve originals and a migration manifest with versions/digests/key binding.
   Pending events must replay offline and survive restart before enabling polls.
6. Quarantine means preserve and disable affected side effects pending recovery,
   not discard data and open a fresh baseline. One corrupt account need not block
   ordinary read-only tools for other accounts.
7. Before native writes, rollback can use untouched old files. After native
   consumption, acknowledgement or sending, an old backup is insufficient:
   export/reconcile new pending work explicitly before rollback. If lossless
   reverse mapping is unavailable, block side-effecting 1.x restart and keep a
   native recovery environment. Never claim transparent downgrade after writes.
8. Old send confirmations are process-memory only and expire at restart. They
   must not be imported or accepted by 2.0; there is no old durable send history
   to reconstruct. Preserve any separately existing native CLAIMED/UNKNOWN store
   rather than treating it as an empty MCP migration target.

## 6. API issue dependencies

All issues were created after checking open and closed issues for duplicates.
They request original reusable library work, not transfer of GPL consumer code.

| Issue | Gap and release gate |
| --- | --- |
| [#22](https://github.com/krzysztofbury/librus-python-api/issues/22) | Explicit modern backend in durable notifications; required for modern-configured notification accounts |
| [#23](https://github.com/krzysztofbury/librus-python-api/issues/23) | Typed external-state bootstrap/import; required for existing-state migration without private codec/SQL coupling |
| [#24](https://github.com/krzysztofbury/librus-python-api/issues/24) | Offline pending-batch/recovery status; required for actionable lost-response and restart recovery |
| [#25](https://github.com/krzysztofbury/librus-python-api/issues/25) | Windows storage/publication; required if Windows disk-feature support is retained |
| [#26](https://github.com/krzysztofbury/librus-python-api/issues/26) | Parked: missing qualifying examples; notes/observation cards stay unavailable/unregistered, not a 2.0.0 blocker |
| [#27](https://github.com/krzysztofbury/librus-python-api/issues/27) | Parked: daily credentialed CI is noncritical and not a 2.0.0 release gate |

Owner scope decision, 2026-10-05: API #22-25 are handled separately by the owner.
Consumer implementation integrates their reviewed, released public contracts.
API #26-27 remain open but parked; no implementation or activation is scheduled
for this cutover. Offline E2E, artifact checks and scoped release qualification
are still required; deferring daily CI does not waive those checks.

Existing C01-C05 communication evidence gaps remain in the API roadmap. They
are not all 2.0 blockers: unsupported archive navigation and independent delivery
acknowledgements must stay explicit rather than grow the migration scope. Populated
completed lessons and dedicated read-once live qualification remain evidence gaps.

The API can change before consumer release. Prefer closing reusable gaps there
over freezing rc1 or growing consumer workarounds. Each API issue needs an exact
merged/released version and consumer acceptance before its MCP gate is checked.
Plan against rc1 now; pin a newer candidate or stable version when gaps land.

## 7. All 18 MCP 2.0 TODO items

| ID | Original item | Current readiness and implementation owner |
| --- | --- | --- |
| A01 | Common collection envelope | Native facts available; MCP defines envelope, limits and honest consistency |
| A02 | Typed record arrays | Available in API; MCP preserves duplicates without display-name maps |
| A03 | Normalize Polish labels | `normalized_fields` implemented; MCP projects stable/unknown/raw values |
| A04 | Attendance units | Native ratios/counts implemented; remove MCP percent conversion |
| A05 | `sort_by` to `scope` | Native view enums implemented; MCP argument rename only |
| A06 | Replace `detail_url`/`href` | Native references available; MCP typed DTO/context checks |
| A07 | Calendar and date inputs | Native integer/date contracts available; MCP schema/default policy |
| A08 | Error categories | Native ErrorKind available; MCP closed mapping and protocol evidence |
| A09 | Remove `all_pages` | Native bounded cursors available; remove redundant consumer aggregation |
| A10 | Remove standalone read-once tool | Native checkpoint workflow available; #22-24 and explicit poll/ack recovery complete the replacement |
| A11 | Rename import package/entry point | MCP work; preserve CLI as `librus_mcp.cli:main`, not obsolete `server:main` target |
| A12 | Mutation tool | Evaluate mutmut 3 on renamed package/Python 3.14; retain invariant proof, no mutation-score target |
| A13 | Explicit/XDG config | MCP work; API construction already explicit |
| A14 | Config migration guide | MCP work; direct major cutover needs no intermediate deprecation release |
| A15 | Remove short-hash mirror | MCP importer then retire runtime dual writes; API store owns subsequent durability |
| A16 | Legacy path collisions | MCP dry-run/import validation; no silent alias rebinding |
| A17 | MCP attachment resources | API bytes/publication available, #25 platform gap; MCP hosting and lifecycle |
| A18 | Byte/context limits | API transport limits available; MCP serializes, measures and bounds protocol payloads |

## 8. License cutover gate

The requested destination is MIT for 2.0.0. The repository originally used MIT
and switched to GPL-3.0-only in commit `1a59c56` to honor the bundled apix license.
Reviewed author identities appear to belong to the project owner, but commit
authorship alone does not prove that every retained snippet/fixture is original.

- Inventory retained runtime, tests, fixtures, documentation and packaged files.
  Identify owner-authored, permissively sourced and GPL-derived material; record
  provenance and required notices. Remove or independently replace any retained
  third-party GPL-only material before the MIT release.
- Treat the user's requested MIT switch as authorization for their own work,
  not authorization to relicense third-party source. Keep API implementation and
  tests independent; requirements may cross the boundary, copied GPL code may not.
- Verify apix is absent from source runtime, direct/transitive dependencies and
  wheel/sdist contents. Review licenses of the complete shipped dependency graph.
- In one coordinated release change, set LICENSE, SPDX metadata/classifier,
  README, SPEC, security/contribution guidance and release notes to MIT for the
  qualified 2.0 line. Preserve applicable copyright/attribution notices.
- Do not rewrite historical tags, release artifacts or 1.x license notices.
   Until the gate passes, keep GPL metadata and do not publish an MIT candidate.

Review completion, 2026-10-05: [LICENSE_REVIEW.md](LICENSE_REVIEW.md) inventories
the new native source, original fixtures, retained project-owned helpers and the
runtime dependency closure including extras/platform markers. The native package
now uses MIT. Historical references were moved outside runtime/build inventories
to `legacy_reference/` with the original GPL license intact. lxml's additional
terms are disclosed; no all-MIT dependency bundle is claimed. Final artifact/host
qualification still applies before publication.

## 9. Cohesive implementation sequence

These are work groups with multiple focused commits/PRs on the 2.0 line, not one
version per commit. No unrelated 1.x compatible release is inserted.

| Group | Work | Exit evidence / dependency |
| --- | --- | --- |
| W0: contract and provenance | Review this plan; freeze schema examples, platform/backend choices and license inventory | Explicit contract decisions and issue dependencies recorded |
| W1: API prerequisites | Owner handles #22-25; integrate their released contracts. #26-27 parked | Reviewed API releases/public contracts; independently authored tests |
| W2: application foundation | Rename package, CLI/config/context-key flow, service/store lifespan and feature gates | Offline startup/config/doctor; one scheduler, no eager login; correct installed entry point |
| W3: ordinary data tools | Native reads, typed DTOs/errors, bounded windows/cursors, calendar and reference changes | Installed MCP-to-API-to-loopback tests and new contract snapshots |
| W4: communication/files | Explicit backend discovery/content, durable preview/send/outcome, native publication and bounded resource contract | Consent/unknown-send/file-boundary integration and platform proof |
| W5: notification upgrade | Public status/poll/ack, old-state inventory/import/rollback, mirror retirement | Real SQLite/process restart and pending-event recovery; requires #22-24 |
| W6: extraction closure | Delete duplicate HTTP/parsers/workers/state code and old dependencies; align docs, typing and mutation tooling | No private API use; approved invariant map and dependency/artifact audit |
| W7: release qualification | Full installed matrix, representative workload, scoped live ordinary reads, license gate | MIT-ready 2.0 candidate, exact tested API on PyPI, rollback documentation |
| W8: final release | Publish exact library prerequisite, then MCP 2.0.0; verify fresh uvx and remote artifact metadata | Remote/tag/version/hash evidence; daily CI is deferred |

W2/W3 can proceed while independent API prerequisites are developed. Do not fill
W4/W5 gaps with consumer implementations that later need moving. Existing native
adapter experiments are evidence references, not a branch to merge wholesale.

Use local `2.0.0.devN` builds during development. Publish `2.0.0rcN` only after
the dependency/provenance/license gates permit MIT artifacts and core acceptance
passes. Final MCP `2.0.0` depends on an exact tested stable API version, preferably
API 1.0.0 or its successor if prerequisites change the contract. Refresh the
lockfile quarantine for that reviewed version; no production Git/path dependency.

## 10. Verification ownership and acceptance

Apply the test-audit rule: preserve observable invariants, not private wrapper
structure or test counts. Existing `test_mcp_stdio_contract.py` exercises actual
stdio but often mocks manager results; it proves 1.x serialization, not the new
HTTP/persistence path. Keep its protocol concerns and replace obsolete shapes.

| Boundary | Retained/new consumer proof | API-owned proof to reuse, not duplicate |
| --- | --- | --- |
| Catalog/DTOs/errors | Reviewed 2.0 schema/annotation snapshot, representative full call results, serialized-byte limits | Native model/parser validation |
| Installed runtime | Real CLI/stdio + exact installed API + original loopback fixture server; no private result mocks | Transport/service request classification |
| Account routing | Four independent logins, overlapping child records/IDs, wrong account/context/reference, one denied login | Cookie isolation, shared scheduler, auth single-flight |
| Traffic/performance | Cold/warm complete summary workloads; compare calls, latency distribution, peak memory, serialized size and active/queued counts | Native per-route budgets/caches/parser load |
| Notification upgrade | Old-format synthetic files -> public import -> stdio poll/ack -> restart; collision/corruption/quarantine and rollback | Native checkpoint/SQLite locking/archive/replay faults |
| Send approval | Exact preview/input/token/backend binding through MCP, feature gate, cancellation/disconnect and outcome lookup | Native durable claims, competing sends and uncertainty |
| Files/resources | MCP destination policy, consent, resource resolution, full JSON limits and installed platform behavior | Credential-free streams, filename safety, publication/cancellation |
| Config/packaging | CLI precedence/XDG/no-cwd, key retention and wrong-key handling, install/wheel/sdist metadata | Explicit library settings and key validation |

Exercise the four-login workload at representative small/full bounded sizes and
under concurrent tools, failures and cancellation. Record the old baseline before
removing it; compare equivalent data needs and explain intentional semantics and
rate-limit differences. Set numeric acceptance thresholds from measured baselines
in W0/W3, not from quiet live windows or made-up speedup targets.

Required checks per owning slice: Ruff/format, strict consumer typing once
configured, security/dependency checks, meaningful unit/integration cases and
actual installed runtime path. Full release checks include Python 3.14, all
declared OS profiles, wheel/sdist installs outside the source tree, CLI routing,
MCP initialization/list/call, state upgrade/recovery and fresh resolver startup.
Update mutation configuration only for safety branches still owned by MCP.

Ordinary CI is offline. New live qualification requires fresh bounded approval
and reconnection where applicable; no sends, message mark-read operations or
read-once consumption for routine checks. API #27 remains the future daily
drift-check owner but is parked and does not block 2.0.0. When resumed, it needs
redacted results and explicit last-run freshness. Current hosted API CI success
is not MCP 2.0 or daily live verification.

### Review decisions before implementation

1. Confirm modern as the new-install messaging default, with explicit legacy
   opt-in and matching native notification support.
2. Retain Windows disk features via #25, or explicitly scope 2.0 to POSIX before
   changing CI, defaults or installation promises.
3. Approve the poll/explicit-ack contract and the proposed tool removals/renames;
   keep unsupported notes disabled/unregistered unless #26 closes.
4. Approve context-key provisioning, configuration precedence, state migration
   blocking behavior and non-transparent rollback after native writes.
5. Close the source provenance inventory before replacing the GPL release license.

### TigerStyle architecture review

- Safety first: native stores own the irreversible boundaries; MCP does not
  recreate a second recovery engine (TigerStyle #1, #12).
- All loops, pages, queues, payloads and resource registries remain bounded;
  a partial result never masquerades as complete (#2, #6).
- Explicit scopes, backend selection, file commit semantics and ratios prevent
  implicit behavior drift (#13, #16, #18).
- Performance comes from service reuse, native coalescing and metadata reuse,
  rather than multiplying workers or merging independent accounts (#14, #15).
- Trade-off: explicit acknowledgement and context-key management add caller
  steps but preserve recovery; native storage reduces duplicated code but exposes
  a platform gap; new DTOs cost migration effort but remove legacy coercion.

The original planning review performed no implementation tests or live calls.
Current implementation verification is recorded separately; it does not imply
completed release qualification, production-state migration or live compatibility.
