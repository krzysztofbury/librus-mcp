# 3. Old-state and resource-snapshot reads are POSIX-only

## Context

Three places read files that another user or process could have swapped:

- migration of 1.x JSON state (`legacy_state.py`, `private_bytes`);
- adoption of 1.x notification files at runtime (`notification_tools.py`);
- resource snapshots of downloaded attachments (`resources.py`).

On POSIX these reads use `O_NOFOLLOW` and descriptor-relative checks of owner
and mode. Windows has no equivalent public no-follow read boundary that this
project has qualified: `lstat` followed by a path open does not prove that
the file read is the one checked, nor its ACL. Windows attachment
publication itself is qualified separately, on NTFS
(`windows_config.py` covers configuration reads).

## Decision

These three reads run only on POSIX hosts. On Windows, old-state migration
fails with a clear error, runtime adoption starts the native notification
store without importing 1.x pending events, and attachments are published
without a resource URI.

## Consequences

- Windows users keep downloads and the native notification store; they lose
  only the import of 1.x state and resource URIs.
- Enabling any of these on Windows needs a qualified no-follow, ACL-checked
  read boundary first, with tests on the Windows CI job.
