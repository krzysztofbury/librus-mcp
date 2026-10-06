"""Persistent context key provisioning, so setup never asks operators for one.

An explicit configured key always wins. Otherwise the key lives beside the native
state it binds, in ``state_dir/context.key``, and backing up that directory keeps
references, cursors and durable history usable. An existing key is never replaced.
"""

import asyncio
import json
import os
import secrets
from pathlib import Path

from pydantic import SecretStr

from librus_mcp.config import AppConfig, ConfigError, notice, read_config_file, valid_key_text

KEY_FILENAME = "context.key"


def key_path(config: AppConfig) -> Path:
    return config.state_dir / KEY_FILENAME


def load_context_key(config: AppConfig) -> AppConfig:
    """Read an existing key file without creating anything."""
    if config.context_key is not None:
        return config
    path = key_path(config)
    if not os.path.lexists(path):
        return config
    data = read_config_file(path)
    value = data.get("context_key")
    if set(data) != {"context_key"} or not isinstance(value, str) or not valid_key_text(value):
        # Never regenerate over an unreadable key: that would orphan durable state.
        raise ConfigError("context key file is invalid; restore it from backup")
    return config.model_copy(update={"context_key": SecretStr(value)})


def _publish_key(directory: Path) -> None:
    body = json.dumps({"context_key": secrets.token_hex(32)}).encode("ascii")
    temporary = directory / f".{KEY_FILENAME}.{secrets.token_hex(8)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(body)
            file.flush()
            os.fsync(file.fileno())
        try:
            # Neither call replaces an existing key: POSIX link and Windows
            # rename both fail when the target exists, so concurrent first
            # starts converge on whichever key was published first.
            if os.name == "posix":
                os.link(temporary, directory / KEY_FILENAME, follow_symlinks=False)
            else:
                os.rename(temporary, directory / KEY_FILENAME)
        except FileExistsError:
            pass
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    if os.name == "posix":
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)


async def provision_context_key(config: AppConfig) -> AppConfig:
    """Return a config with a persistent key, creating it once when absent."""
    config = load_context_key(config)
    if config.context_key is not None:
        return config
    from librus_mcp.runtime import prepare_private_directory

    await prepare_private_directory(config.state_dir)
    try:
        await asyncio.to_thread(_publish_key, config.state_dir)
    except OSError:
        raise ConfigError("cannot create the context key in the state directory") from None
    provisioned = load_context_key(config)
    if provisioned.context_key is None:
        raise ConfigError("cannot create the context key in the state directory")
    notice("created a persistent context key in the state directory; include it in backups")
    return provisioned
