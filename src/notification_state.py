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
import stat
import sys
from itertools import islice
from pathlib import Path
from uuid import uuid4

from librus_apix.notifications import NotificationIds
from librus_apix.schedule import RecentEvent

from src.response_limits import MAX_RESPONSE_BODY_BYTES

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
MAX_PENDING_SCHEDULE_EVENTS = 500
MAX_PENDING_SCHEDULE_BATCH_BYTES = 128 * 1024
# Parsed event text can approach the full response size and JSON escaping can
# expand it. Keep the durable file bounded while preserving any accepted body.
MAX_PENDING_SCHEDULE_EVENT_BYTES = 2 * MAX_RESPONSE_BODY_BYTES + 64 * 1024
MAX_PENDING_SCHEDULE_FILES = 512
MAX_NOTIFICATION_ID_LENGTH = 1024
MAX_NOTIFICATION_STATE_FILE_BYTES = 4 * 1024 * 1024
STATE_DIRECTORY_MODE = 0o700
STATE_FILE_MODE = 0o600
SCHEDULE_EVENT_FIELDS = ("date_added", "type", "data")


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
    _ensure_state_directory(path.parent)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(tmp_path, flags, STATE_FILE_MODE)
    try:
        if os.name == "posix":
            os.fchmod(descriptor, STATE_FILE_MODE)
        temporary_file = os.fdopen(descriptor, "wb")
        descriptor = -1
        with temporary_file:
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(tmp_path, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        tmp_path.unlink(missing_ok=True)


def _ensure_state_directory(path: Path) -> None:
    if os.name != "posix":
        path.mkdir(parents=True, exist_ok=True)
        return
    created = False
    try:
        path.mkdir(parents=True, mode=STATE_DIRECTORY_MODE)
        created = True
    except FileExistsError:
        pass
    if path.is_symlink():
        raise ValueError(f"notification state directory must not be a symlink: {path}")
    if created:
        os.chmod(path, STATE_DIRECTORY_MODE, follow_symlinks=False)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    expected_identity: tuple[int, int] | None = None
    try:
        descriptor = os.open(path, flags)
    except PermissionError:
        # A private directory may have lost owner-read permission. Inspect it
        # through a private parent descriptor so another user cannot swap the
        # path between validation and repair.
        parent_descriptor = os.open(path.parent, flags)
        try:
            parent_status = os.fstat(parent_descriptor)
            if parent_status.st_uid != os.geteuid() or stat.S_IMODE(parent_status.st_mode) & 0o022:
                raise PermissionError(
                    f"notification state directory could not be secured automatically: {path}"
                )
            status = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
            if stat.S_ISLNK(status.st_mode):
                raise ValueError(f"notification state directory must not be a symlink: {path}")
            if not stat.S_ISDIR(status.st_mode):
                raise ValueError(f"notification state path must be a directory: {path}")
            if status.st_uid != os.geteuid():
                raise PermissionError(
                    f"notification state directory must be owned by the current user: {path}"
                )
            expected_identity = (status.st_dev, status.st_ino)
            try:
                os.chmod(path.name, STATE_DIRECTORY_MODE, dir_fd=parent_descriptor)
            except OSError as exc:
                raise PermissionError(
                    f"notification state directory could not be secured automatically: {path}"
                ) from exc
            descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
        finally:
            os.close(parent_descriptor)
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISDIR(status.st_mode):
            raise ValueError(f"notification state path must be a directory: {path}")
        if expected_identity is not None and (status.st_dev, status.st_ino) != expected_identity:
            raise RuntimeError(f"notification state directory changed during repair: {path}")
        if status.st_uid != os.geteuid():
            raise PermissionError(
                f"notification state directory must be owned by the current user: {path}"
            )
        if created or stat.S_IMODE(status.st_mode) != STATE_DIRECTORY_MODE:
            try:
                os.fchmod(descriptor, STATE_DIRECTORY_MODE)
            except OSError as exc:
                raise PermissionError(
                    f"notification state directory could not be secured automatically: {path}"
                ) from exc
            if stat.S_IMODE(os.fstat(descriptor).st_mode) != STATE_DIRECTORY_MODE:
                raise PermissionError(
                    f"notification state directory could not be secured automatically: {path}"
                )
    finally:
        os.close(descriptor)


def _read_bounded_bytes(path: Path, max_bytes: int = MAX_NOTIFICATION_STATE_FILE_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError(f"notification state at {path} must be a regular file") from None
        raise
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"notification state at {path} must be a regular file")
        with os.fdopen(descriptor, "rb") as file:
            descriptor = -1
            payload = file.read(max_bytes + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(payload) > max_bytes:
        raise ValueError(f"notification state at {path} is too large (maximum {max_bytes} bytes)")
    return payload


def _validate_id_category(category: object, key: str) -> list[str]:
    if not isinstance(category, list):
        raise TypeError(f"ids.{key} must be a list")
    if len(category) > MAX_IDS_PER_CATEGORY:
        raise ValueError(f"ids.{key} is unexpectedly large")
    for notification_id in category:
        if not isinstance(notification_id, str):
            raise TypeError(f"ids.{key} contains a non-string notification ID")
        if not notification_id or len(notification_id) > MAX_NOTIFICATION_ID_LENGTH:
            raise ValueError(
                f"ids.{key} contains a notification ID outside the 1 to "
                f"{MAX_NOTIFICATION_ID_LENGTH} character limit"
            )
    return category


def _fsync_directory(path: Path) -> None:
    """Persist directory entry changes where the platform exposes directory fsync."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _schedule_event_payload(event: RecentEvent) -> dict[str, str]:
    payload = {field: getattr(event, field) for field in SCHEDULE_EVENT_FIELDS}
    for field, value in payload.items():
        if not isinstance(value, str):
            raise TypeError(f"schedule event {field} must be a string")
    return payload


def schedule_event_id(event: RecentEvent) -> str:
    """Return a stable identity covering every user-visible event field."""
    canonical = json.dumps(
        _schedule_event_payload(event), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _pending_schedule_path(state_dir: Path, alias: str, event: RecentEvent) -> Path:
    state_name = _state_path(Path(state_dir), alias).name.removesuffix(".notifications.json")
    return Path(state_dir) / f"{state_name}.pending-schedule.{schedule_event_id(event)}.json"


def _pending_schedule_batch_path(state_dir: Path, alias: str, payload: bytes) -> Path:
    state_name = _state_path(Path(state_dir), alias).name.removesuffix(".notifications.json")
    digest = hashlib.sha256(payload).hexdigest()
    return Path(state_dir) / f"{state_name}.pending-schedule.batch.{digest}.json"


def _encoded_schedule_event(event: RecentEvent) -> bytes:
    return json.dumps(
        _schedule_event_payload(event),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _publish_pending_schedule_batch(state_dir: Path, alias: str, events: list[RecentEvent]) -> None:
    encoded_events: list[bytes] = []
    for event in events:
        encoded_event = _encoded_schedule_event(event)
        encoded_event_file_size = len(encoded_event) + 2
        if encoded_event_file_size > MAX_PENDING_SCHEDULE_EVENT_BYTES:
            raise ValueError("pending schedule event is too large to checkpoint safely")
        encoded_events.append(encoded_event)
    if not encoded_events:
        return
    payload = b"[" + b",".join(encoded_events) + b"]"
    if len(payload) > MAX_PENDING_SCHEDULE_EVENT_BYTES:
        raise ValueError("pending schedule event batch is too large to checkpoint safely")
    _atomic_publish(_pending_schedule_batch_path(state_dir, alias, payload), payload)


def save_pending_schedule_events(state_dir: Path, alias: str, events: list[RecentEvent]) -> None:
    """Checkpoint a complete read-once result as one bounded atomic batch."""
    state_dir = Path(state_dir)
    _ensure_state_directory(state_dir)
    _publish_pending_schedule_batch(state_dir, alias, events)


def _pending_events_from_file(
    path: Path, state_dir: Path, alias: str
) -> tuple[list[RecentEvent], int]:
    encoded_payload = _read_bounded_bytes(path, MAX_PENDING_SCHEDULE_EVENT_BYTES)
    try:
        payload = json.loads(encoded_payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"corrupt pending schedule event at {path}") from error
    payloads = payload if isinstance(payload, list) else [payload]
    if not payloads:
        raise ValueError(f"unexpected pending schedule event schema at {path}")
    events: list[RecentEvent] = []
    for event_payload in payloads:
        if not isinstance(event_payload, dict) or set(event_payload) != set(SCHEDULE_EVENT_FIELDS):
            raise ValueError(f"unexpected pending schedule event schema at {path}")
        if not all(isinstance(event_payload[field], str) for field in SCHEDULE_EVENT_FIELDS):
            raise ValueError(f"unexpected pending schedule event schema at {path}")
        events.append(RecentEvent(**event_payload))
    if isinstance(payload, list):
        if path != _pending_schedule_batch_path(state_dir, alias, encoded_payload):
            raise ValueError(f"pending schedule event digest mismatch at {path}")
    elif path != _pending_schedule_path(state_dir, alias, events[0]):
        raise ValueError(f"pending schedule event digest mismatch at {path}")
    return events, len(encoded_payload)


def load_pending_schedule_events(state_dir: Path, alias: str) -> list[RecentEvent]:
    """Load one bounded batch preserved after an interrupted transaction."""
    state_dir = Path(state_dir)
    state_name = _state_path(state_dir, alias).name.removesuffix(".notifications.json")
    paths = islice(
        state_dir.glob(f"{state_name}.pending-schedule*.json"), MAX_PENDING_SCHEDULE_FILES
    )
    events: list[RecentEvent] = []
    event_ids: set[str] = set()
    batch_size_bytes = 2
    for path in paths:
        file_events, _ = _pending_events_from_file(path, state_dir, alias)
        for event in file_events:
            event_id = schedule_event_id(event)
            if event_id in event_ids:
                continue
            encoded_event_size = len(_encoded_schedule_event(event))
            separator_size = 1 if events else 0
            next_batch_size_bytes = batch_size_bytes + separator_size + encoded_event_size
            if events and (
                next_batch_size_bytes > MAX_PENDING_SCHEDULE_BATCH_BYTES
                or len(events) == MAX_PENDING_SCHEDULE_EVENTS
            ):
                return events
            events.append(event)
            event_ids.add(event_id)
            batch_size_bytes = next_batch_size_bytes
    return events


def clear_pending_schedule_events(state_dir: Path, alias: str, events: list[RecentEvent]) -> None:
    """Delete only events handled by a successful state transaction."""
    state_dir = Path(state_dir)
    cleared_ids = {schedule_event_id(event) for event in events}
    for event in events:
        try:
            _pending_schedule_path(state_dir, alias, event).unlink(missing_ok=True)
        except OSError as error:
            # The response remains successful; retaining a spool entry can cause
            # a duplicate later, while failing here could hide already saved data.
            print(
                f"librus-mcp: could not clear pending schedule event for '{alias}': {error}",
                file=sys.stderr,
            )
    state_name = _state_path(state_dir, alias).name.removesuffix(".notifications.json")
    batch_paths = list(
        islice(
            state_dir.glob(f"{state_name}.pending-schedule.batch.*.json"),
            MAX_PENDING_SCHEDULE_FILES,
        )
    )
    for path in batch_paths:
        try:
            spooled_events, _ = _pending_events_from_file(path, state_dir, alias)
            remaining = [
                event for event in spooled_events if schedule_event_id(event) not in cleared_ids
            ]
            if len(remaining) < len(spooled_events):
                _publish_pending_schedule_batch(state_dir, alias, remaining)
                path.unlink(missing_ok=True)
        except (OSError, TypeError, ValueError) as error:
            print(
                f"librus-mcp: could not clear pending schedule batch for '{alias}': {error}",
                file=sys.stderr,
            )
    if events:
        try:
            _fsync_directory(state_dir)
        except OSError as error:
            print(
                f"librus-mcp: could not persist pending schedule cleanup for '{alias}': {error}",
                file=sys.stderr,
            )


def _migrate_legacy_state_path(state_dir: Path, alias: str) -> Path:
    path = _state_path(state_dir, alias)
    legacy_path = _legacy_state_path(state_dir, alias)
    if legacy_path is None or not legacy_path.exists():
        return path
    try:
        legacy_payload = _read_bounded_bytes(legacy_path)
    except FileNotFoundError:
        return path
    current_payload = None
    if path.exists():
        try:
            current_payload = _read_bounded_bytes(path)
        except ValueError:
            pass
    if current_payload != legacy_payload:
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
    _ensure_state_directory(state_path.parent)
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if os.name == "posix":
            os.fchmod(descriptor, STATE_FILE_MODE)
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


def verify_notification_state_storage(state_dir: Path) -> None:
    """Exercise atomic state persistence and locking with isolated diagnostic files."""
    state_dir = Path(state_dir)
    alias = f"doctor-{os.getpid()}-{uuid4().hex}"
    state_path = _state_path(state_dir, alias)
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    descriptor: int | None = None
    empty_ids = NotificationIds(
        grades=[], attendance=[], messages=[], announcements=[], schedule=[], homework=[]
    )
    try:
        save_notification_ids(state_dir, alias, empty_ids)
        if load_notification_ids(state_dir, alias) is None:
            raise RuntimeError("notification state verification could not read its test data")
        descriptor = try_acquire_notification_state_lock(state_dir, alias)
        if descriptor is None:
            raise RuntimeError("notification state verification could not acquire its test lock")
    finally:
        primary_error = sys.exception()
        cleanup_error: OSError | RuntimeError | None = None
        if descriptor is not None:
            try:
                release_notification_state_lock(descriptor)
            except (OSError, RuntimeError) as error:
                cleanup_error = error
        for path in (lock_path, state_path):
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                cleanup_error = cleanup_error or error
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


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
    try:
        path = _migrate_legacy_state_path(Path(state_dir), alias)
    except (TypeError, ValueError) as error:
        print(f"librus-mcp: {error}, rebuilding", file=sys.stderr)
        return None
    if not path.exists():
        return None
    try:
        data = json.loads(_read_bounded_bytes(path))
    except json.JSONDecodeError, UnicodeDecodeError:
        print(f"librus-mcp: corrupt notification state at {path}, rebuilding", file=sys.stderr)
        return None
    except ValueError as error:
        print(f"librus-mcp: {error}, rebuilding", file=sys.stderr)
        return None
    if not isinstance(data, dict) or set(data.keys()) != set(CATEGORY_KEYS):
        print(f"librus-mcp: unexpected notification state schema at {path}", file=sys.stderr)
        return None
    try:
        for key in CATEGORY_KEYS:
            _validate_id_category(data[key], key)
    except (TypeError, ValueError) as error:
        print(
            f"librus-mcp: unexpected notification state schema at {path}: {error}",
            file=sys.stderr,
        )
        return None
    return NotificationIds(**data)


def save_notification_ids(state_dir: Path, alias: str, ids: NotificationIds) -> None:
    """Persist seen notification IDs atomically. The temp filename is unique per
    call so concurrent writers cannot interleave bytes in a shared temp file;
    last rename wins. Each category is pruned to its newest tail."""
    assert isinstance(ids, NotificationIds), "ids must be a NotificationIds instance"
    payload: dict[str, list[str]] = {}
    for key in CATEGORY_KEYS:
        category = _validate_id_category(getattr(ids, key), key)
        payload[key] = category[-MAX_SAVED_IDS_PER_CATEGORY:]
    assert set(payload.keys()) == set(CATEGORY_KEYS), "payload must cover all categories"
    state_dir = Path(state_dir)
    path = _state_path(state_dir, alias)
    _ensure_state_directory(path.parent)
    encoded_payload = json.dumps(payload).encode("utf-8")
    if len(encoded_payload) > MAX_NOTIFICATION_STATE_FILE_BYTES:
        raise ValueError("notification state payload is too large to persist safely")
    legacy_path = _legacy_state_path(state_dir, alias)
    if legacy_path is not None:
        _atomic_publish(legacy_path, encoded_payload)
    _atomic_publish(path, encoded_payload)
