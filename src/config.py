import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

MAX_ALIAS_LENGTH = 80
MAX_CONFIG_FILE_BYTES = 1024 * 1024
ALIAS_PATTERN = r"^(?:[^\s\p{C}]|[^\s\p{C}](?:[^\s\p{C}]| )*[^\s\p{C}])$"


class ConfigError(ValueError):
    """A redacted, actionable configuration error safe to show at startup."""


def _default_state_dir() -> Path:
    return Path.home() / ".librus-mcp" / "state"


def _default_download_dir() -> Path:
    return Path.home() / ".librus-mcp" / "downloads"


def validate_alias(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("account alias must be a non-empty string")
    if value != value.strip():
        raise ValueError("account alias must not have surrounding whitespace")
    if not value.isprintable():
        raise ValueError("account alias must contain only printable characters")
    if len(value) > MAX_ALIAS_LENGTH:
        raise ValueError(f"account alias must contain at most {MAX_ALIAS_LENGTH} characters")
    return value


def _validation_summary(error: ValidationError) -> str:
    details: list[str] = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"])
        details.append(f"{location}: {item['msg']}" if location else item["msg"])
    return "; ".join(details)


def _environment_validation_summary(error: ValidationError) -> str:
    details: list[str] = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        location = list(item["loc"])
        if location and location[0] in EnvironmentSettings.model_fields:
            field = EnvironmentSettings.model_fields[str(location[0])]
            location[0] = field.validation_alias or location[0]
        field = ".".join(str(part) for part in location)
        details.append(f"{field}: {item['msg']}" if field else item["msg"])
    return "; ".join(details)


def _validated_config(data: Any, source: str) -> "AppConfig":
    try:
        return AppConfig.model_validate(data)
    except ValidationError as error:
        raise ConfigError(f"invalid {source}: {_validation_summary(error)}") from None


class AccountConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    alias: str
    username: str
    password: SecretStr

    @field_validator("alias")
    @classmethod
    def _valid_alias(cls, value: str) -> str:
        return validate_alias(value)

    @field_validator("username")
    @classmethod
    def _non_blank_username(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("account username must not be blank")
        return value

    @field_validator("password", mode="before")
    @classmethod
    def _non_blank_password(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("account password must not be blank")
        return value


class FeaturesConfig(BaseModel):
    """Feature gates for optional MCP tools. Verified read tools default on;
    behaviour notes stay experimental and send_message writes to the school,
    so both default off.
    Unknown keys are rejected: a typo silently falling back to defaults
    would undermine the write gate."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    notifications: bool = True
    attachments: bool = True
    behaviour_notes: bool = False
    send_message: bool = False


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    accounts: list[AccountConfig]
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    state_dir: Path = Field(default_factory=_default_state_dir)
    download_dir: Path = Field(default_factory=_default_download_dir)

    @field_validator("state_dir", mode="before")
    @classmethod
    def _default_state_path(cls, value: object) -> object:
        return _default_state_dir() if value is None or value == "" else value

    @field_validator("download_dir", mode="before")
    @classmethod
    def _default_download_path(cls, value: object) -> object:
        return _default_download_dir() if value is None or value == "" else value

    @field_validator("state_dir", "download_dir")
    @classmethod
    def _expand_path(cls, value: Path) -> Path:
        return value.expanduser()

    @field_validator("accounts")
    @classmethod
    def _unique_aliases(cls, accounts: list[AccountConfig]) -> list[AccountConfig]:
        """Duplicate aliases would silently route every call to the first
        matching account — a wrong-child data leak, not a cosmetic issue."""
        if len(accounts) == 0:
            raise ValueError("accounts must contain at least one account")
        seen: set[str] = set()
        for account in accounts:
            if account.alias in seen:
                raise ValueError(f"duplicate account alias: '{account.alias}'")
            seen.add(account.alias)
        return accounts


class EnvironmentSettings(BaseSettings):
    """Typed operator overrides from LIBRUS_* environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    accounts: list[AccountConfig] | None = Field(None, validation_alias="LIBRUS_ACCOUNTS")
    config_path: Path | None = Field(None, validation_alias="LIBRUS_CONFIG")
    features: dict[str, Any] | None = Field(None, validation_alias="LIBRUS_FEATURES")
    state_dir: Path | None = Field(None, validation_alias="LIBRUS_STATE_DIR")
    download_dir: Path | None = Field(None, validation_alias="LIBRUS_DOWNLOAD_DIR")


def _load_environment_settings() -> EnvironmentSettings:
    try:
        settings = EnvironmentSettings()
    except SettingsError as error:
        message = str(error)
        source = "LIBRUS environment variable"
        for field in ("accounts", "features"):
            if f'field "{field}"' in message:
                source = f"LIBRUS_{field.upper()}"
                break
        raise ConfigError(f"{source} contains invalid JSON") from None
    except ValidationError as error:
        raise ConfigError(
            f"invalid environment: {_environment_validation_summary(error)}"
        ) from None
    if "LIBRUS_ACCOUNTS" in os.environ and settings.accounts is None:
        raise ConfigError("LIBRUS_ACCOUNTS must be a JSON array, not null")
    if "LIBRUS_FEATURES" in os.environ and settings.features is None:
        raise ConfigError("LIBRUS_FEATURES must be a JSON object, not null")
    return settings


def _apply_environment_settings(config: AppConfig, settings: EnvironmentSettings) -> AppConfig:
    data = config.model_dump()
    if settings.features is not None:
        unknown_keys = set(settings.features) - set(FeaturesConfig.model_fields)
        if unknown_keys:
            raise ConfigError(
                f"LIBRUS_FEATURES contains unknown keys: {sorted(unknown_keys)}. "
                f"Valid keys: {sorted(FeaturesConfig.model_fields)}"
            )
        data["features"] = config.features.model_dump() | settings.features
    if settings.state_dir is not None:
        data["state_dir"] = settings.state_dir
    if settings.download_dir is not None:
        data["download_dir"] = settings.download_dir
    return _validated_config(data, "configuration")


def _resolve_config_path(config_path: Path | None) -> str:
    """Find secrets.json: LIBRUS_CONFIG env var, then CWD, then project root."""
    if config_path is not None:
        path = str(config_path.expanduser())
        if not os.path.exists(path):
            raise ConfigError(f"LIBRUS_CONFIG points to {path!r}, which does not exist")
        return path

    # Try current working directory first (where the user launched the server).
    cwd_path = os.path.join(os.getcwd(), "secrets.json")
    if os.path.exists(cwd_path):
        return cwd_path

    # Fallback: project root (one level up from src/).
    project_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "secrets.json"
    )
    if os.path.exists(project_path):
        return project_path

    raise ConfigError(
        "credentials not found; set LIBRUS_CONFIG to a private secrets.json file "
        "or provide LIBRUS_ACCOUNTS"
    )


def _check_credential_file(file: BinaryIO, path: str) -> None:
    status = os.fstat(file.fileno())
    if not stat.S_ISREG(status.st_mode):
        raise ConfigError(f"credential path {path!r} must be a regular file")
    mode = stat.S_IMODE(status.st_mode)
    if os.name == "posix" and mode & 0o077:
        raise ConfigError(
            f"credential file {path!r} is accessible by group or other users "
            f"(mode {mode:04o}); run: chmod 600 {path!r}"
        )


def _load_from_file(path: str) -> AppConfig:
    """Load config from a secrets.json file."""
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags)
        file = os.fdopen(descriptor, "rb")
        descriptor = -1
        with file:
            _check_credential_file(file, path)
            payload = file.read(MAX_CONFIG_FILE_BYTES + 1)
    except ConfigError:
        raise
    except OSError as error:
        raise ConfigError(f"cannot read credential file {path!r}: {error.strerror}") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(payload) > MAX_CONFIG_FILE_BYTES:
        raise ConfigError(
            f"credential file {path!r} is too large (maximum {MAX_CONFIG_FILE_BYTES} bytes)"
        )
    try:
        decoded_payload = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigError(f"credential file {path!r} contains invalid UTF-8") from None
    try:
        data = json.loads(decoded_payload)
    except json.JSONDecodeError:
        raise ConfigError(f"credential file {path!r} contains invalid JSON") from None
    if not isinstance(data, dict):
        raise ConfigError(f"credential file {path!r} must contain a JSON object")
    return _validated_config(data, f"credential file {path!r}")


def load_config() -> AppConfig:
    """Load config from env var or file. Priority: LIBRUS_ACCOUNTS > LIBRUS_CONFIG > file.
    Other LIBRUS_* settings override their matching file values."""
    settings = _load_environment_settings()
    if settings.accounts is not None:
        config = _validated_config({"accounts": settings.accounts}, "LIBRUS_ACCOUNTS")
        return _apply_environment_settings(config, settings)
    path = _resolve_config_path(settings.config_path)
    config = _load_from_file(path)
    # stderr, never stdout (MCP transport). Lets the operator spot a surprise
    # secrets.json picked up from an unexpected working directory.
    print(f"librus-mcp: loading credentials from {path!r}", file=sys.stderr)
    return _apply_environment_settings(config, settings)
