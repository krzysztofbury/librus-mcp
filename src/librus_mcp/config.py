"""Explicit application configuration; no working-directory credential discovery."""

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from librus_python_api import AccountCredentials, MessagingBackend
from librus_python_api.exceptions import LibrusError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

MAX_CONFIG_BYTES = 1024 * 1024
MAX_ACCOUNTS = 16
# Portable JSON Schema regex; Unicode printability is additionally checked below.
# Rust-only Unicode properties cannot be compiled by common MCP JSON validators.
ALIAS_PATTERN = (
    r"^(?:[^\s\x00-\x1f\x7f]|[^\s\x00-\x1f\x7f](?:[^\s\x00-\x1f\x7f]| )*[^\s\x00-\x1f\x7f])$"
)


class ConfigError(ValueError):
    """A closed, redacted startup error."""


class AccountConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    alias: str = Field(min_length=1, max_length=80, pattern=ALIAS_PATTERN)
    username: SecretStr = Field(repr=False)
    password: SecretStr = Field(repr=False)
    expected_owner_id: str | None = Field(default=None, repr=False)
    expected_student_id: str | None = Field(default=None, repr=False)
    messaging_backend: MessagingBackend = MessagingBackend.MODERN

    @field_validator("alias")
    @classmethod
    def printable_alias(cls, value: str) -> str:
        if not value.isprintable():
            raise ValueError("invalid alias")
        return value

    def credentials(self) -> AccountCredentials:
        return AccountCredentials(
            login=self.username,
            password=self.password,
            expected_owner_id=self.expected_owner_id,
            expected_student_id=self.expected_student_id,
        )


class FeaturesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    # Development slice: unavailable features fail explicitly when enabled.
    notifications: bool = False
    attachments: bool = False
    send_message: bool = False
    behaviour_notes: bool = False


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    accounts: tuple[AccountConfig, ...] = Field(min_length=1, max_length=MAX_ACCOUNTS)
    context_key: SecretStr = Field(repr=False)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    state_dir: Path = Field(default_factory=lambda: Path.home() / ".librus-mcp" / "state")
    download_dir: Path = Field(default_factory=lambda: Path.home() / ".librus-mcp" / "downloads")

    @field_validator("context_key")
    @classmethod
    def valid_context_key(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value.get_secret_value()):
            raise ValueError("context_key must encode 32 bytes as hexadecimal")
        return value

    @field_validator("accounts")
    @classmethod
    def distinct_accounts(cls, value: tuple[AccountConfig, ...]) -> tuple[AccountConfig, ...]:
        if len({account.alias for account in value}) != len(value):
            raise ValueError("duplicate account alias")
        # Use the library's supported credential validation, not a second policy.
        for account in value:
            account.credentials()
        return value

    @field_validator("state_dir", "download_dir")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        value = value.expanduser()
        if not value.is_absolute():
            raise ValueError("directory must be absolute")
        return value

    def key_bytes(self) -> bytes:
        return bytes.fromhex(self.context_key.get_secret_value())

    def require_supported_features(self) -> None:
        if self.features.behaviour_notes:
            raise ConfigError("behaviour notes are unavailable until API qualification")


def _json(value: str | bytes, *, source: str) -> Any:
    if len(value) > MAX_CONFIG_BYTES:
        raise ConfigError(f"{source} exceeds the configuration size limit")
    try:
        return json.loads(value)
    except ValueError, RecursionError:
        raise ConfigError(f"{source} contains invalid JSON") from None


def read_config_file(path: Path) -> dict[str, Any]:
    if os.name == "nt":
        from librus_mcp.windows_config import read_private_config

        data = _json(read_private_config(path, MAX_CONFIG_BYTES), source="configuration file")
        if not isinstance(data, dict):
            raise ConfigError("configuration file must contain a JSON object")
        return data
    # Bound special-file reads and reject symlinks on platforms with O_NOFOLLOW.
    descriptor = -1
    try:
        if path.is_symlink():
            raise ConfigError("configuration must not be a symlink")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(descriptor, "rb") as file:
            descriptor = -1
            status = os.fstat(file.fileno())
            if not stat.S_ISREG(status.st_mode):
                raise ConfigError("configuration must be a regular file")
            if os.name == "posix" and (
                status.st_uid != os.getuid() or stat.S_IMODE(status.st_mode) & 0o077
            ):
                raise ConfigError("configuration must be owner-private; use chmod 600")
            data = _json(file.read(MAX_CONFIG_BYTES + 1), source="configuration file")
    except OSError:
        raise ConfigError(
            "cannot read configuration file; check its path and permissions"
        ) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(data, dict):
        raise ConfigError("configuration file must contain a JSON object")
    return data


def load_config(config_path: Path | None = None) -> AppConfig:
    """CLI path wins; otherwise explicit environment selectors must not conflict."""
    selected = config_path or (
        Path(os.environ["LIBRUS_CONFIG"]) if "LIBRUS_CONFIG" in os.environ else None
    )
    if config_path is None and selected is not None and "LIBRUS_ACCOUNTS" in os.environ:
        raise ConfigError("choose LIBRUS_CONFIG or LIBRUS_ACCOUNTS, not both")
    if selected is not None:
        data = read_config_file(selected.expanduser())
    elif "LIBRUS_ACCOUNTS" in os.environ:
        data = {"accounts": _json(os.environ["LIBRUS_ACCOUNTS"], source="LIBRUS_ACCOUNTS")}
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        if not root.is_absolute():
            raise ConfigError("XDG_CONFIG_HOME must be absolute")
        data = read_config_file(root / "librus-mcp" / "config.json")
    # Only these explicit operator overrides apply to a selected credential source.
    for name, field in (
        ("LIBRUS_CONTEXT_KEY", "context_key"),
        ("LIBRUS_STATE_DIR", "state_dir"),
        ("LIBRUS_DOWNLOAD_DIR", "download_dir"),
    ):
        if name in os.environ:
            data[field] = os.environ[name]
    if "LIBRUS_FEATURES" in os.environ:
        overrides = _json(os.environ["LIBRUS_FEATURES"], source="LIBRUS_FEATURES")
        existing = data.get("features", {})
        if not isinstance(overrides, dict) or not isinstance(existing, dict):
            raise ConfigError("features must be a JSON object")
        data["features"] = existing | overrides
    try:
        config = AppConfig.model_validate(data)
    except ValidationError, LibrusError:
        raise ConfigError(
            "invalid configuration: check accounts, unique aliases, context_key, features and paths"
        ) from None
    # Do not silently enable missing contracts or pretend the partial rewrite is final.
    config.require_supported_features()
    return config
