"""Bounded runtime-only attachment snapshots, not a filesystem browsing service."""

import hashlib
import os
import re
import secrets
import stat
import time
from pathlib import Path

from librus_python_api.exceptions import ErrorKind, LibrusError
from librus_python_api.files import PublishedAttachment

MAX_RESOURCE_BYTES = 256 * 1024
MAX_RESOURCES = 32
RESOURCE_TTL_SECONDS = 900


class AttachmentResources:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._entries: dict[str, tuple[float, bytes]] = {}

    def _expire(self) -> None:
        now = time.monotonic()
        self._entries = {key: item for key, item in self._entries.items() if item[0] > now}

    def snapshot(self, saved: PublishedAttachment) -> str | None:
        # Windows publication is native/NTFS-qualified. Resource snapshots remain
        # POSIX-only until a public Windows no-follow read boundary is qualified.
        if (
            os.name != "posix"
            or not hasattr(os, "O_NOFOLLOW")
            or saved.size_bytes > MAX_RESOURCE_BYTES
        ):
            return None
        self._expire()
        if len(self._entries) >= MAX_RESOURCES:
            return None
        if saved.path.parent != self.directory:
            raise LibrusError(ErrorKind.STORAGE)
        directory = descriptor = -1
        try:
            directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            status = os.fstat(directory)
            if status.st_uid != os.geteuid() or stat.S_IMODE(status.st_mode) & 0o077:
                raise LibrusError(ErrorKind.STORAGE)
            descriptor = os.open(
                saved.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
            status = os.fstat(descriptor)
            if (
                not stat.S_ISREG(status.st_mode)
                or status.st_uid != os.geteuid()
                or stat.S_IMODE(status.st_mode) & 0o077
            ):
                raise LibrusError(ErrorKind.STORAGE)
            with os.fdopen(descriptor, "rb") as file:
                descriptor = -1
                body = file.read(MAX_RESOURCE_BYTES + 1)
            if len(body) != saved.size_bytes or hashlib.sha256(body).hexdigest() != saved.sha256:
                raise LibrusError(ErrorKind.STORAGE)
        except OSError:
            raise LibrusError(ErrorKind.STORAGE) from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if directory >= 0:
                os.close(directory)
        token = secrets.token_urlsafe(32)
        self._entries[token] = (time.monotonic() + RESOURCE_TTL_SECONDS, body)
        return f"librus-attachment://files/{token}"

    def read(self, token: str) -> bytes:
        if re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None:
            raise LibrusError(ErrorKind.INVALID_INPUT)
        self._expire()
        item = self._entries.get(token)
        if item is None:
            raise LibrusError(ErrorKind.INVALID_INPUT)
        return item[1]

    def close(self) -> None:
        self._entries.clear()
