import json
import os
import sys
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccountConfig(BaseModel):
    alias: str
    username: str
    password: str

    @field_validator("alias", "username", "password")
    @classmethod
    def _non_blank(cls, value: str, info) -> str:
        """A blank alias would make an account unaddressable; blank credentials
        would fail only later, deep inside the login flow, with a worse error."""
        if not value.strip():
            raise ValueError(f"account {info.field_name} must not be blank")
        return value


class FeaturesConfig(BaseModel):
    """Feature gates for optional MCP tools. Read tools default on;
    send_message is a write action against the school, so it defaults off.
    Unknown keys are rejected: a typo silently falling back to defaults
    would undermine the write gate."""

    model_config = ConfigDict(extra="forbid")

    notifications: bool = True
    attachments: bool = True
    behaviour_notes: bool = True
    send_message: bool = False


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accounts: List[AccountConfig]
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    state_dir: Optional[str] = None
    download_dir: Optional[str] = None

    @field_validator("accounts")
    @classmethod
    def _unique_aliases(cls, accounts: List[AccountConfig]) -> List[AccountConfig]:
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
        raise ValueError("LIBRUS_ACCOUNTS contains invalid JSON")
    if not isinstance(accounts, list):
        raise ValueError("LIBRUS_ACCOUNTS must be a JSON array")
    if len(accounts) == 0:
        raise ValueError("LIBRUS_ACCOUNTS must contain at least one account")
    return AppConfig(accounts=accounts)


def _apply_features_env(config: AppConfig) -> AppConfig:
    """Overlay LIBRUS_FEATURES env var (JSON object) on top of configured features."""
    if "LIBRUS_FEATURES" not in os.environ:
        return config
    raw = os.environ["LIBRUS_FEATURES"]
    try:
        overrides = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("LIBRUS_FEATURES contains invalid JSON")
    if not isinstance(overrides, dict):
        raise ValueError("LIBRUS_FEATURES must be a JSON object")
    unknown_keys = set(overrides) - set(FeaturesConfig.model_fields)
    if unknown_keys:
        raise ValueError(
            f"LIBRUS_FEATURES contains unknown keys: {sorted(unknown_keys)}. "
            f"Valid keys: {sorted(FeaturesConfig.model_fields)}"
        )
    merged = config.features.model_dump() | overrides
    config.features = FeaturesConfig(**merged)
    return config


def _resolve_config_path() -> str:
    """Find secrets.json: LIBRUS_CONFIG env var, then CWD, then project root."""
    if "LIBRUS_CONFIG" in os.environ:
        path = os.environ["LIBRUS_CONFIG"]
        if not os.path.exists(path):
            raise FileNotFoundError(f"LIBRUS_CONFIG points to '{path}' which does not exist")
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

    raise FileNotFoundError(
        "secrets.json not found. Provide credentials via one of:\n"
        "  1. LIBRUS_ACCOUNTS env var (JSON array of accounts)\n"
        "  2. LIBRUS_CONFIG env var (path to secrets.json)\n"
        "  3. secrets.json in the current directory"
    )


def _load_from_file(path: str) -> AppConfig:
    """Load config from a secrets.json file."""
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return AppConfig(**data)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON in {path}")
        except Exception as e:
            raise ValueError(f"Error loading config from {path}: {e}")


def load_config() -> AppConfig:
    """Load config from env var or file. Priority: LIBRUS_ACCOUNTS > LIBRUS_CONFIG > file.
    LIBRUS_FEATURES (JSON object) overrides the features section from any source."""
    if "LIBRUS_ACCOUNTS" in os.environ:
        return _apply_features_env(_load_from_env_accounts())
    path = _resolve_config_path()
    # stderr, never stdout (MCP transport). Lets the operator spot a surprise
    # secrets.json picked up from an unexpected working directory.
    print(f"librus-mcp: loading credentials from {path}", file=sys.stderr)
    return _apply_features_env(_load_from_file(path))
