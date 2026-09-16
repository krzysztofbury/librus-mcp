import json
import os
import stat
import sys
from typing import Any, BinaryIO

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)

MAX_ALIAS_LENGTH = 80
MAX_CONFIG_FILE_BYTES = 1024 * 1024
ALIAS_PATTERN = r"^(?:[^\s\p{C}]|[^\s\p{C}](?:[^\s\p{C}]| )*[^\s\p{C}])$"


class ConfigError(ValueError):
    """A redacted, actionable configuration error safe to show at startup."""


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
    """Feature gates for optional MCP tools. Read tools default on;
    send_message is a write action against the school, so it defaults off.
    Unknown keys are rejected: a typo silently falling back to defaults
    would undermine the write gate."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    notifications: bool = True
    attachments: bool = True
    behaviour_notes: bool = True
    send_message: bool = False


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    accounts: list[AccountConfig]
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    state_dir: str | None = None
    download_dir: str | None = None

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


def _load_from_env_accounts() -> AppConfig:
    """Parse LIBRUS_ACCOUNTS env var: a JSON array of account objects."""
    raw = os.environ["LIBRUS_ACCOUNTS"]
    try:
        accounts = json.loads(raw)
    except json.JSONDecodeError:
        raise ConfigError("LIBRUS_ACCOUNTS contains invalid JSON") from None
    if not isinstance(accounts, list):
        raise ConfigError("LIBRUS_ACCOUNTS must be a JSON array")
    if len(accounts) == 0:
        raise ConfigError("LIBRUS_ACCOUNTS must contain at least one account")
    return _validated_config({"accounts": accounts}, "LIBRUS_ACCOUNTS")


def _apply_features_env(config: AppConfig) -> AppConfig:
    """Overlay LIBRUS_FEATURES env var (JSON object) on top of configured features."""
    if "LIBRUS_FEATURES" not in os.environ:
        return config
    raw = os.environ["LIBRUS_FEATURES"]
    try:
        overrides = json.loads(raw)
    except json.JSONDecodeError:
        raise ConfigError("LIBRUS_FEATURES contains invalid JSON") from None
    if not isinstance(overrides, dict):
        raise ConfigError("LIBRUS_FEATURES must be a JSON object")
    unknown_keys = set(overrides) - set(FeaturesConfig.model_fields)
    if unknown_keys:
        raise ConfigError(
            f"LIBRUS_FEATURES contains unknown keys: {sorted(unknown_keys)}. "
            f"Valid keys: {sorted(FeaturesConfig.model_fields)}"
        )
    merged = config.features.model_dump() | overrides
    try:
        config.features = FeaturesConfig(**merged)
    except ValidationError as error:
        raise ConfigError(f"invalid LIBRUS_FEATURES: {_validation_summary(error)}") from None
    return config


def _resolve_config_path() -> str:
    """Find secrets.json: LIBRUS_CONFIG env var, then CWD, then project root."""
    if "LIBRUS_CONFIG" in os.environ:
        path = os.environ["LIBRUS_CONFIG"]
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
    LIBRUS_FEATURES (JSON object) overrides the features section from any source."""
    if "LIBRUS_ACCOUNTS" in os.environ:
        return _apply_features_env(_load_from_env_accounts())
    path = _resolve_config_path()
    config = _apply_features_env(_load_from_file(path))
    # stderr, never stdout (MCP transport). Lets the operator spot a surprise
    # secrets.json picked up from an unexpected working directory.
    print(f"librus-mcp: loading credentials from {path!r}", file=sys.stderr)
    return config
