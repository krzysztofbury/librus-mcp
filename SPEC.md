# Native 2.0 application specification

The installed import package is `librus_mcp`; the console entry is
`librus_mcp.cli:main`. All releases before 2.0 use apix. The native package is MIT;
unshipped 1.x references retain their scoped GPL license. See
[LICENSE_REVIEW.md](LICENSE_REVIEW.md) and [MIGRATION_2_0.md](MIGRATION_2_0.md).

## Ownership

- API: authentication, shared traffic scheduling, transport, parsing, native
  references/cursors/budgets, send claims/outcomes, notification checkpoint/replay,
  bootstrap/archive/recovery and complete file publication.
- MCP: explicit configuration/aliases, feature registration, consent, typed wire
  projections, whole-result/catalog bounds, resource snapshots and interpretation
  of historical MCP state files.
- One `Runtime` and native `LibrusService` per async lifespan. No eager login,
  merged child sessions, private API imports, transport adapters or fallback.
- Optional stores close through the lifespan stack. Normal reads remain usable
  for a quarantined legacy-state account; new notification polls do not.

## Safety boundaries

Invalid aliases, dates and bound references fail before upstream requests.
Native errors become closed codes without causes, HTML, credentials or inputs.
School text is untrusted, inert data. Partial output never masquerades as complete.
The full duplicated MCP result is capped at 512 KiB.

Received-body opening, exact-input send redemption and fresh read-once consumption
are separate consent boundaries. Durable states, not memory dictionaries, prevent
send replays. Notifications require explicit delivery acknowledgement. Malformed
checkpoints and uncertainty remain recoverable, not discarded.

Native publication is the file commit point. Resource hosting is optional and
bounded to 32 snapshots of at most 256 KiB, expiring after 900 seconds or restart.
A snapshot failure after commit returns the local file and native digest without
a resource URI. Windows supports native NTFS publication, not snapshot reads.

POSIX config files are owner-private, regular and no-follow. Windows config files
are read through pinned local-NTFS handles with conservative owner/ACL, reparse and
hardlink checks. Neither path repairs a shared credential source implicitly.

## Development

Use the pinned released native dependency and original synthetic wires in
`tests_native/`. Test MCP-owned serialization, routing and lifecycle effects through
the actual installed CLI/stdio path. Do not copy API/client fixtures or duplicate
API-owned parser/storage proof. Offline PR jobs never authenticate to live Librus.
Live qualification requires separately scoped approval and shared invocation
budgets. Do not publish, deploy or migrate production state as routine testing.

Keep GPL historical references in `legacy_reference/`, outside build inventories
and imports. They are not executable 2.0 tests. Their supported historical baseline
is the v1.7.0 tree, not a restoration of apix to the 2.0 environment.
