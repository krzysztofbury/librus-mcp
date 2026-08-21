"""Per-alias persistence of librus-apix NotificationIds.

The notifications module diffs current data against previously seen IDs.
The MCP server is stateless between sessions, so seen IDs are stored as one
JSON file per student alias under the state directory.
"""

import errno
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

from librus_apix.notifications import NotificationIds

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

CATEGORY_KEYS = ("grades", "attendance", "messages", "announcements", "schedule", "homework")
MAX_IDS_PER_CATEGORY = 10_000
# Upstream appends to seen-ID lists forever; keep only the newest tail so the
# file cannot grow without bound. Old items never reappear in the
# since-last-login views the diff reads from, so pruning them is safe.
MAX_SAVED_IDS_PER_CATEGORY = 500
MAX_STATE_ALIAS_PREFIX_LENGTH = 80
MAX_LEGACY_FILENAME_LENGTH = 190


def resolve_state_dir(config_state_dir: str | None) -> Path:
    """Resolve state dir. Priority: LIBRUS_STATE_DIR env > config > default."""
    if "LIBRUS_STATE_DIR" in os.environ:
        return Path(os.environ["LIBRUS_STATE_DIR"]).expanduser()
    if config_state_dir:
        return Path(config_state_dir).expanduser()
    return Path.home() / ".librus-mcp" / "state"


def _state_path(state_dir: Path, alias: str) -> Path:
    assert alias, "alias must not be empty"
    assert isinstance(alias, str), "alias must be a string"
    safe_alias = re.sub(r"[^A-Za-z0-9_-]", "_", alias)
    if safe_alias == alias:
        # Filename-safe aliases keep their pre-0.5 filename so existing
        # seen-notification state survives the upgrade.
        return state_dir / f"{alias}.notifications.json"
    # Sanitization is lossy ('child/a' and 'child?a' both become 'child_a'),
    # so distinct aliases could share a file and cross-report notifications.
    # A digest of the original alias keeps sanitized names collision-free.
    digest = hashlib.sha256(alias.encode("utf-8")).hexdigest()
    return state_dir / (f"{safe_alias[:MAX_STATE_ALIAS_PREFIX_LENGTH]}.{digest}.notifications.json")


def _legacy_state_path(state_dir: Path, alias: str) -> Path | None:
    safe_alias = re.sub(r"[^A-Za-z0-9_-]", "_", alias)
    if safe_alias == alias:
        return None
    digest = hashlib.sha256(alias.encode("utf-8")).hexdigest()[:8]
    filename = f"{safe_alias}.{digest}.notifications.json"
    if len(filename.encode("utf-8")) > MAX_LEGACY_FILENAME_LENGTH:
        return None
    return state_dir / filename


def _atomic_publish(path: Path, payload: bytes) -> None:
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        tmp_path.write_bytes(payload)
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _migrate_legacy_state_path(state_dir: Path, alias: str) -> Path:
    path = _state_path(state_dir, alias)
    legacy_path = _legacy_state_path(state_dir, alias)
    if legacy_path is None or not legacy_path.exists():
        return path
    try:
        legacy_payload = legacy_path.read_bytes()
    except FileNotFoundError:
        return path
    if not path.exists() or path.read_bytes() != legacy_payload:
        # Keep the legacy file as a compatibility mirror. New processes lock
        # it too, so an older process can safely update state during rollout.
        _atomic_publish(path, legacy_payload)
    return path


def try_acquire_notification_state_lock(state_dir: Path, alias: str) -> int | None:
    """Try to acquire the advisory lock shared by local MCP processes.

    Returns None while another process owns the lock. The async manager polls
    this non-blocking function, so task cancellation cannot orphan a lock.
    """
    state_dir = Path(state_dir)
    state_path = _legacy_state_path(state_dir, alias) or _state_path(state_dir, alias)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if _try_lock_descriptor(descriptor):
            return descriptor
    except Exception:
        os.close(descriptor)
        raise
    os.close(descriptor)
    return None


def release_notification_state_lock(descriptor: int) -> None:
    """Release a descriptor returned by try_acquire_notification_state_lock."""
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        elif msvcrt is not None:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            raise RuntimeError("notification state locks are unsupported on this platform")
    finally:
        os.close(descriptor)


def _try_lock_descriptor(descriptor: int) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise
        return True
    if msvcrt is not None:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    raise RuntimeError("notification state locks are unsupported on this platform")


def load_notification_ids(state_dir: Path, alias: str) -> NotificationIds | None:
    """Load seen notification IDs for an alias. Returns None when the file is
    missing or unusable (corrupt JSON, wrong schema) — callers then rebuild the
    baseline. Filesystem errors propagate: masking them as 'first run' would
    silently re-report every notification."""
    path = _migrate_legacy_state_path(Path(state_dir), alias)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"librus-mcp: corrupt notification state at {path}, rebuilding", file=sys.stderr)
        return None
    if not isinstance(data, dict) or set(data.keys()) != set(CATEGORY_KEYS):
        print(f"librus-mcp: unexpected notification state schema at {path}", file=sys.stderr)
        return None
    for key in CATEGORY_KEYS:
        if not isinstance(data[key], list):
            print(f"librus-mcp: unexpected notification state schema at {path}", file=sys.stderr)
            return None
    return NotificationIds(**data)


def save_notification_ids(state_dir: Path, alias: str, ids: NotificationIds) -> None:
    """Persist seen notification IDs atomically. The temp filename is unique per
    call so concurrent writers cannot interleave bytes in a shared temp file;
    last rename wins. Each category is pruned to its newest tail."""
    assert isinstance(ids, NotificationIds), "ids must be a NotificationIds instance"
    payload: dict[str, list] = {}
    for key in CATEGORY_KEYS:
        category = getattr(ids, key)
        assert isinstance(category, list), f"ids.{key} must be a list"
        assert len(category) <= MAX_IDS_PER_CATEGORY, f"ids.{key} unexpectedly large"
        payload[key] = category[-MAX_SAVED_IDS_PER_CATEGORY:]
    assert set(payload.keys()) == set(CATEGORY_KEYS), "payload must cover all categories"
    state_dir = Path(state_dir)
    path = _state_path(state_dir, alias)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded_payload = json.dumps(payload).encode("utf-8")
    legacy_path = _legacy_state_path(state_dir, alias)
    if legacy_path is not None:
        _atomic_publish(legacy_path, encoded_payload)
    _atomic_publish(path, encoded_payload)
