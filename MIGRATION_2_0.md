# MCP 2.0: breaking backend and contract change

## Release boundary

**All librus-mcp versions before 2.0 use `librus-apix`.** Starting with the 2.0
development line, the installed server uses only the independently implemented
[`librus-python-api`](https://github.com/krzysztofbury/librus-python-api).
There is no apix dependency, compatibility backend or fallback.

This is a **breaking change**, not a drop-in dependency upgrade. Tool names,
arguments, result schemas, effects, configuration and notification acknowledgement
change. Do not assume a 1.x assistant integration or state directory can be reused.
Library and MCP version numbers are independent: the initial development build
pins the published native library `1.0.0`.

The current MCP version is **2.0.0.dev1**, an unpublished native release candidate.
It is not the final 2.0 release and has not been published by this migration work.
Published 1.x remains the existing apix-backed implementation. Use an explicit
version when selecting a backend; an unversioned install currently resolves 1.x.

## Implemented native contracts

The wheel contains `librus_mcp`, not the generic `src` package. The console entry
point is `librus_mcp.cli:main`. One async lifespan owns one native service across
all configured accounts, without login during startup, tool listing or local checks.
Native service defaults bound combined rate, burst, active requests and queues.

| 1.x contract | Current native contract |
| --- | --- |
| `list_students` with `result: [alias]` | `list_accounts` with `items: [{account_alias}]` |
| `student_alias` | `account_alias`, an independent login rather than a child identity |
| `sort_by` for grade/attendance selection | `scope`: `all`, `week`, `last_login` |
| Name-keyed/grouped grade output and converted apix fields | Typed record arrays, native grade symbols, raw school summaries and explicit availability |
| Flattened profile result | `data` and `observation`, including login owner and represented student identity |
| Final-grade legacy mappings | `items` with midterm/predicted/annual availability and raw values |
| Runtime exception text | `isError=true` with a closed `error.code`; no raw input/page/cause text |

The default development catalog has 22 tools. Enabling all supported optional
features gives 30 tools, each with typed input/output schemas:

| Family | Tools |
| --- | --- |
| Accounts/profile | `list_accounts`, `get_student_information` |
| Grades | `get_final_grades`, `get_grades`, `get_grades_window` |
| Attendance/frequency | `get_attendance`, `get_attendance_window`, `get_attendance_detail`, `get_attendance_frequency`, `get_subject_frequency` |
| Calendar/homework | `get_agenda`, `get_agenda_detail`, `get_homework`, `get_homework_detail`, `get_timetable` |
| Other academic reads | `get_announcements`, `get_completed_lessons` |
| Messaging/directory | `get_messages`, `get_message_content`, `get_recipient_types`, `get_recipient_choices`, `get_recipients` |
| Optional durable sends | `preview_message`, `send_message`, `get_send_outcome`, `get_send_history` |
| Optional attachments | `download_attachment` and `librus-attachment://files/{token}` resource template |
| Optional notifications | `get_new_notifications`, `get_notification_status`, `acknowledge_notifications` |

Dates use ISO civil dates (`YYYY-MM-DD`), not Unix timestamps. Frequency results
keep native ratios in `0..1` or `null`, with attended/total/excluded/unknown counts.
Calendar months use integer `year`/`month`; timetable weeks require a Monday.
Homework defaults to today through today+14 in Warsaw; supplied dates must be
paired. Native validation bounds the range. School wall times are not guessed UTC.

Grade/attendance windows accept `limit` and a presentation cursor bound to the
account context, selected dates/scope and full selected source. A changed source
returns `STALE_CURSOR`; changed query/context returns `INVALID_INPUT`.
These cursors re-read native collections, not stored snapshots or upstream page
offsets. Undated summaries remain available through the whole-collection tools.
Completed lessons use the native date/account-bound cursor plus `limit` and
`max_pages`. Continuations are best effort, not a transactional school snapshot.
Agenda/homework details require the bound references returned by their lists.

Messaging uses the explicitly configured backend, never automatic fallback.
`get_messages` returns summaries and backend/account/context-bound cursors and
references. `limit`, `max_pages` and modern `page_size` bound each call. Received
body reads require `allow_mark_read=true`; listing never grants that consent.
Sent content can be opened without received-message consent. Body and directory
text remain inert, untrusted data. `get_recipient_choices` is legacy-only and
returns `UNSUPPORTED_CAPABILITY` on a modern account. Select a supported bound
reference from `get_recipient_types` for `get_recipients`.

Whole-page reads expose best-effort pagination metadata without a cursor or
silent truncation. Oversized complete MCP results fail with `LIMIT`. Session
selection tools are not annotated read-only; message content is explicitly
annotated with its possible mark-read effect. Input and output schemas must
compile in the real client's JSON Schema validator, not just Pydantic.

Notifications, attachments and sending are integrated but default off. Enable
each explicitly through `features` or `LIBRUS_FEATURES`. Behaviour notes remain
unavailable and enabling them fails at startup. Explicit opt-in is the current
2.0 policy, not an unresolved feature gate. The declared backend/platform profiles
and MIT review passed qualification; exact evidence and the scope of subsequent
changes are recorded in [NATIVE_TEST_PLAN.md](NATIVE_TEST_PLAN.md). Final
version/tag/publication and fresh remote installation remain a separate step.

### Durable sends

Select recipients through the configured backend. Add the returned recipient
envelope's `context` and `backend` to each native recipient reference; submit
`message={recipients, subject, body}` to `preview_message`. The exact preview is
persisted without HTTP, with a token expiring after five minutes. After human
approval, supply the same message and token to `send_message` with `confirm=true`.
The token proves payload binding, not that a human approved it. Neither call can
independently enforce an agent's claimed human approval.

The API owns single-use durable claims and outcomes. Changed payloads invalidate
the claim; replay cannot dispatch again. `get_send_outcome` and `get_send_history`
are offline and survive restart. ACCEPTED means the upstream accepted the send,
not that a recipient read it. CLAIMED/UNKNOWN require reconciliation, never
automatic retry. The native store retains hashes and outcomes, not plain bodies
or confirmation tokens. Old in-memory 1.x tokens cannot be imported.

### Attachment publication/resources

`download_attachment` requires an account/context/backend-bound message reference,
a numeric file identifier, a display filename and a byte cap. It does not open
message bodies or accept arbitrary URLs/destination paths. The API sanitizes the
filename and publishes complete files into `download_dir/native-v2`. Incomplete
streams publish nothing; a cancellation/error around the atomic commit point
can leave a complete file, but joined workers do not continue after shutdown.

The result provides the private server-local path, byte count, MIME hint and digest.
On POSIX, files up to 256 KiB can also get an inert binary resource snapshot.
The registry holds at most 32 snapshots for 15 minutes, clears on shutdown and
never reads a new path or refetches upstream during resource reads. Capture uses
owner-private, regular, no-follow file checks plus size/digest matching. Files
remain the explicit fallback after expiry/capacity exhaustion, for larger files,
or on Windows where resource snapshot reads are not yet qualified. A server-local
path is not automatically accessible to a remote MCP host.

### Notification delivery

`get_new_notifications` requires explicit distinct categories and stages a native
receipt. Ordinary polls may authenticate and change session filters, but never
open received bodies. Fresh `agenda` consumption requires
`allow_consume_events=true` each time. Pending identical category/backend polls
replay locally until acknowledgement, including after restart. Different category
tuples reject rather than discarding a staged batch.

Call `acknowledge_notifications` with the batch context and receipt only after
actual delivery. Even an empty batch needs acknowledgement. The latest committed
receipt is idempotent; foreign/older receipts reject. Delivery is at-least-once,
not exactly-once. `get_notification_status` is offline and exposes pending/raw/
uncertain facts without clearing them or registering a missing context. Retained
malformed checkpoints block another consume even with renewed consent.

Consumer staging bounds are 128 items and 48 KiB encoded batches, with agenda
replay slices capped at 128 events/32 KiB. These are lower than API defaults to
keep both structured and text MCP copies below the 512 KiB whole-result cap.
Oversized history fails closed, never silently truncates or acknowledges data.

## Configuration changes

- Configuration comes from CLI `--config`, otherwise one of `LIBRUS_CONFIG` or
  `LIBRUS_ACCOUNTS`, otherwise `$XDG_CONFIG_HOME/librus-mcp/config.json`
  (default `~/.config/librus-mcp/config.json`). CLI selection wins. Conflicting
  environment credential selectors fail. Cwd/project `secrets.json` discovery is
  removed; pass an old file explicitly only after updating its contents.
- Retain `alias`, `username`, `password` account fields. Optional
  `expected_owner_id` / `expected_student_id` bind identity expectations;
  `messaging_backend` is `modern` by default or explicitly `legacy`. Backend
  selection does not merge sessions for accounts representing the same child.
- Supply a persistent, random 32-byte `context_key` as 64 hexadecimal characters
  in the private configuration, or in `LIBRUS_CONTEXT_KEY`. Run
  `librus-mcp --generate-context-key` once and save its output privately. This
  explicit command does not load credentials or write files. Do not regenerate
  the key on startup, derive it from credentials or use example/test keys.
- Keep the key backed up with native state and identical across cooperating
  processes. Changing the key, login, alias or source origins changes native binding.
  The application owns key provisioning; a separate private-key-file option is
  deferred rather than introducing another implicit filesystem workflow now.
- `LIBRUS_FEATURES`, `LIBRUS_STATE_DIR`, `LIBRUS_DOWNLOAD_DIR` remain validated
  operator overrides. Feature booleans are strict; directories must be absolute.
  Enabled durable features provision private native directories at startup; the
  default read-only profile does not. Absent ancestors, such as `~/.librus-mcp` on
  a fresh host, are created owner-only. Existing directories are used as found and
  must be owned by the current user without group/other access: a 1.x
  `download_dir` created as `0755` needs `chmod 700` before enabling attachments.
  Otherwise startup stops with one redacted line before serving. Native databases
  live in `state_dir/native-v2`.
  Serving never imports or advances 1.x files.
- Credential files must be regular and nonsymlink files, up to 1 MiB. POSIX files
  must belong to the current user and disallow group/other access (`chmod 600`).
  Windows requires local fixed NTFS with a private ACL, verified through pinned
  handles before credential reads. Shared/null ACLs, hardlinks and reparse-point
  components fail closed; existing permissions are not repaired implicitly.
- `--version` requires no config. `--check-config` is offline and does not sign in
  or mutate state. Keep stdout exclusively for protocol messages during serving.
- `--doctor` reports configuration/features offline without provisioning state.
  `--doctor --doctor-storage` explicitly provisions the private state parent and
  exercises disposable native SQLite stores there, then cleans the diagnostic
  directory. It never opens the real native-v2 store or old JSON history. This
  probes native setup/transactions, not every disk-full/crash/lock scenario.

## State and rollback warning

**Do not enable a fresh native notification baseline over existing 1.x history.**
Polls reject with `STORAGE` when matching old files remain in the configured state
root. That per-account quarantine does not disable other accounts' polls or
ordinary academic reads. Keep the old source separate from the new configured
state directory. Do not move or delete originals just to bypass the guard.

The POSIX-only `migrate-state` command inventories private, regular, no-follow
sources without network or target writes. It handles safe names, full-hash names,
short-hash mirrors and single/batch pending spools. Conflicting mirrors, duplicate
IDs/overlapping events, wrong digests and oversized inputs reject without reset.

```bash
librus-mcp --config /private/native-config.json migrate-state --dry-run \
  --source-dir /private/old-state --account-alias example
librus-mcp --config /private/native-config.json migrate-state --dry-run \
  --source-dir /private/old-state --account-alias example --mapping-file /private/plan.json
librus-mcp --config /private/native-config.json migrate-state --apply \
  --source-dir /private/old-state --account-alias example --mapping-file /private/plan.json \
  --confirm-writers-stopped --confirm-login-binding-reviewed
```

The private mapping JSON has `account_alias`, the service-owned native `context`
digest, exact `source_files` filename-to-SHA256 fingerprints and `mappings`.
Every baseline ID needs one `{category, source_identifier, native_identifier,
evidence}` entry; old `schedule` becomes native `agenda`. Use independently
established native canonical IDs, never a hash of an opaque legacy ID. Modern
message identities include backend/folder. `native_identifier=null` reports an
unmapped entry and blocks apply. Source IDs beyond the public API's 256-character
bootstrap bound also require manual recovery. The CLI cannot validate the truth
of an operator's evidence string or login review. Inventory-only dry-run reports
counts, not IDs. A mapping dry-run checks binding/coverage/fingerprints but does
not open the target or promise that native bootstrap will accept all history.

Apply requires a separate native target root and an empty native account context.
It calls public native bootstrap, preserves every source file and creates private
prepared/completed manifests. An interrupted/failed apply may retain the prepared
manifest or successfully staged native history; inspect status before retrying,
never delete native uncertainty/history to force another import. Historical
events replay offline with original text and `imported_history` provenance,
without fabricated identity/observation metadata. Import does not acknowledge them.

The current operator recovery commands are POSIX-only.
`notification-state --account-alias example --status` inspects native recovery
offline. `--export-file /private/new-archive.json` exclusively writes a private
JSON envelope containing the exact public native archive as base64, its version
and account context. It never parses native archive internals or overwrites an
existing destination. Public API `NotificationArchive`/`import_archive` can restore
that payload into an empty native recovery store; automatic restoration or reverse
1.x migration is not provided. `--resolve-uncertain-consume --accept-possible-loss`
is an explicit loss-consenting operator action, not a tool or an automatic retry.
Native guards reject resolution when raw/pending work still exists.

Keep old files untouched and stop 1.x writers before migration. Native
consumption, acknowledgement and sends require a deliberate export/reconciliation
before rollback; an old backup is insufficient after native writes. See the full
[implementation plan](MCP_2_0_PLAN.md) and [verification ownership](NATIVE_TEST_PLAN.md).

## Licensing

The native 2.0 package and its new tests/documentation now use MIT after the
retained-source and runtime-dependency inventory in [LICENSE_REVIEW.md](LICENSE_REVIEW.md).
The apix-backed references were moved to `legacy_reference/` under their original
GPL-3.0-only license and are excluded from the wheel/sdist. Removing apix alone
was not treated as authority to relicense external work. Dependencies retain their
own terms, including lxml's additional notices. Historical licenses, tags and
release artifacts are not rewritten. No MCP 2.0 release has been published.

Windows configuration files require a local fixed NTFS path and a conservative
private ACL. Only the current user, SYSTEM and Administrators may have allow
entries; a null/broad ACL, hardlinks and reparse-point components are rejected.
The reader pins the path and validates the opened handle before reading secrets.
Existing permissions are never repaired automatically.

API notes/observation cards (#26) and daily credentialed CI (#27) remain parked.

## Explicit live qualification

Ordinary CI stays offline. With separate live authorization, the source/sdist
includes `scripts/qualify_native.py` for real stdio qualification:

```bash
uv run python scripts/qualify_native.py --live --config /absolute/private/config.json
uv run python scripts/qualify_native.py --live --phase communication --config /absolute/private/config.json
uv run python scripts/qualify_native.py --live --phase homework_history --config /absolute/private/config.json
```

Each invocation shares an API budget across accounts/calls: 160 upstream
requests, 360 seconds and 16 MiB total response bytes, in addition to the shared
native scheduler limits. Authentication can advance last-login baselines and
read filters can change. Qualification never sends, consumes read-once events,
opens received bodies, downloads files or writes durable state. It neither edits
the supplied config nor provisions a deployment key. An absent context key gets
a memory-only key for that disposable qualification server.

The report contains status codes and coverage only, not credentials, aliases,
school text or references. Empty collections and missing detail/sent references
are reported honestly. Expected unsupported operations are distinguished from
successful reads. A completed run does not prove every variant or nonempty
response. Library, platform and durable-workflow qualification remain separate.
