"""Conservative old-state discovery, without importing the unshipped 1.x runtime."""

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from librus_python_api import NotificationCategory, RecentScheduleEvent
from librus_python_api.exceptions import ErrorKind, LibrusError

from librus_mcp.config import ConfigError

MAX_DIRECTORY_ENTRIES = 4096


def legacy_stems(alias: str) -> tuple[str, ...]:
    """Names specified by the historical MCP file contract, not native identities."""
    prefix = "".join(
        character if character.isascii() and (character.isalnum() or character in "_-") else "_"
        for character in alias
    )
    if prefix == alias:
        return (alias,)
    digest = hashlib.sha256(alias.encode("utf-8")).hexdigest()
    return (f"{prefix[:80]}.{digest}", f"{prefix}.{digest[:8]}")


def legacy_files(directory: Path, alias: str) -> tuple[Path, ...]:
    stems = legacy_stems(alias)
    found: list[Path] = []
    try:
        with os.scandir(directory) as entries:
            for count, entry in enumerate(entries, start=1):
                if count > MAX_DIRECTORY_ENTRIES:
                    raise LibrusError(ErrorKind.LIMIT)
                if any(
                    entry.name == stem + ".notifications.json"
                    or re.fullmatch(
                        re.escape(stem) + r"\.pending-schedule(?:\.[^.]+)*\.json", entry.name
                    )
                    for stem in stems
                ):
                    found.append(directory / entry.name)
    except FileNotFoundError:
        return ()
    except OSError:
        raise LibrusError(ErrorKind.STORAGE) from None
    return tuple(sorted(found))


def restrict_own_files(paths: tuple[Path, ...]) -> None:
    """Make the current user's own regular 1.x files 0600 before validation.

    Some 1.x versions wrote notification files as 0644. Files owned by another
    user, symlinks and special files are left for the private read to reject.
    """
    if os.name != "posix":
        return
    for path in paths:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            status = os.fstat(descriptor)
            if (
                stat.S_ISREG(status.st_mode)
                and status.st_uid == os.geteuid()
                and stat.S_IMODE(status.st_mode) & 0o077
            ):
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)


@dataclass(frozen=True)
class LegacyInventory:
    files: dict[str, str]
    baseline: tuple[tuple[NotificationCategory, str], ...]
    pending_events: tuple[RecentScheduleEvent, ...]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError("duplicate JSON field in migration input")
        result[key] = value
    return result


def private_bytes(path: Path, maximum: int) -> bytes:
    # This consumer-owned old-file boundary is intentionally POSIX-only. Do not
    # pretend that lstat plus a Windows path open provides no-follow/ACL proof.
    if os.name != "posix":
        raise ConfigError("old-state migration requires a qualified POSIX host")
    directory = descriptor = -1
    try:
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        parent = os.fstat(directory)
        if parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) & 0o077:
            raise ConfigError("migration inputs require owner-private directories")
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_uid != os.geteuid()
            or stat.S_IMODE(status.st_mode) & 0o077
        ):
            raise ConfigError("migration inputs require owner-private regular files")
        with os.fdopen(descriptor, "rb") as file:
            descriptor = -1
            body = file.read(maximum + 1)
        if len(body) > maximum:
            raise ConfigError("migration input exceeds its byte limit")
        return body
    except OSError:
        raise ConfigError("cannot safely read migration input") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory >= 0:
            os.close(directory)


def migration_json(body: bytes) -> object:
    def validate_text(value: object) -> None:
        if isinstance(value, str):
            value.encode("utf-8")
        elif isinstance(value, list):
            for item in value:
                validate_text(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                validate_text(key)
                validate_text(item)

    try:
        result = json.loads(body, object_pairs_hook=_unique_object)
        # JSON permits escaped lone surrogates, but native canonical UTF-8 does
        # not. Reject them before digests/manifests can expose exception inputs.
        validate_text(result)
        return result
    except ValueError, RecursionError:
        raise ConfigError("invalid migration JSON") from None


def inventory_legacy(directory: Path, alias: str) -> LegacyInventory:
    """Validate every selected old file, with no silent truncation or deduplication."""
    paths = legacy_files(directory, alias)
    if not paths:
        raise ConfigError("no legacy state found for the selected account")
    if len(paths) > 512:
        raise ConfigError("legacy file count exceeds the inventory limit")
    baseline_bytes: bytes | None = None
    baseline: list[tuple[NotificationCategory, str]] = []
    events: list[RecentScheduleEvent] = []
    event_keys: set[tuple[str, str, str]] = set()
    files: dict[str, str] = {}
    total = 0
    categories = {
        "grades": NotificationCategory.GRADES,
        "attendance": NotificationCategory.ATTENDANCE,
        "messages": NotificationCategory.MESSAGES,
        "announcements": NotificationCategory.ANNOUNCEMENTS,
        "schedule": NotificationCategory.AGENDA,
        "homework": NotificationCategory.HOMEWORK,
    }
    for path in paths:
        body = private_bytes(path, 4 * 1024 * 1024)
        total += len(body)
        if total > 16 * 1024 * 1024:
            raise ConfigError("legacy inventory exceeds its total byte limit")
        files[path.name] = hashlib.sha256(body).hexdigest()
        payload = migration_json(body)
        if path.name.endswith(".notifications.json"):
            if not isinstance(payload, dict) or set(payload) != set(categories):
                raise ConfigError("invalid legacy baseline schema")
            if baseline_bytes is not None:
                if baseline_bytes != body:
                    raise ConfigError("conflicting legacy baseline mirrors")
                continue
            baseline_bytes = body
            for key, category in categories.items():
                identifiers = payload[key]
                if (
                    not isinstance(identifiers, list)
                    or len(identifiers) > 10000
                    or any(
                        not isinstance(identifier, str) or not 1 <= len(identifier) <= 1024
                        for identifier in identifiers
                    )
                ):
                    raise ConfigError("invalid legacy baseline identifiers")
                if len(set(identifiers)) != len(identifiers):
                    raise ConfigError("duplicate legacy baseline identifiers")
                baseline.extend((category, identifier) for identifier in identifiers)
            continue
        batch = payload if isinstance(payload, list) else [payload]
        if not batch:
            raise ConfigError("empty legacy pending batch")
        for value in batch:
            if (
                not isinstance(value, dict)
                or set(value) != {"date_added", "type", "data"}
                or any(not isinstance(text, str) for text in value.values())
            ):
                raise ConfigError("invalid legacy pending event schema")
            event = RecentScheduleEvent(
                date_added=value["date_added"], type=value["type"], data=value["data"]
            )
            event_key = (event.date_added, event.type, event.data)
            if event_key in event_keys:
                raise ConfigError("overlapping legacy pending events require review")
            event_keys.add(event_key)
            events.append(event)
            if len(events) > 128:
                raise ConfigError("pending history exceeds the native batch item limit")
        digest_bytes = (
            body
            if isinstance(payload, list)
            else json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        )
        digest = hashlib.sha256(digest_bytes).hexdigest()
        kind = ".pending-schedule.batch." if isinstance(payload, list) else ".pending-schedule."
        if path.name not in {stem + kind + digest + ".json" for stem in legacy_stems(alias)}:
            raise ConfigError("legacy pending file digest mismatch")
    return LegacyInventory(files=files, baseline=tuple(baseline), pending_events=tuple(events))
