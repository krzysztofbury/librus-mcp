import json
import os
from typing import List
from pydantic import BaseModel


class AccountConfig(BaseModel):
    alias: str
    username: str
    password: str


class AppConfig(BaseModel):
    accounts: List[AccountConfig]


def _load_from_env_accounts() -> AppConfig:
    """Parse LIBRUS_ACCOUNTS env var: a JSON array of account objects."""
    raw = os.environ["LIBRUS_ACCOUNTS"]
    try:
        accounts = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("LIBRUS_ACCOUNTS contains invalid JSON")
    assert isinstance(accounts, list), "LIBRUS_ACCOUNTS must be a JSON array"
    assert len(accounts) > 0, "LIBRUS_ACCOUNTS must contain at least one account"
    return AppConfig(accounts=accounts)


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
    """Load config from env var or file. Priority: LIBRUS_ACCOUNTS > LIBRUS_CONFIG > file."""
    if "LIBRUS_ACCOUNTS" in os.environ:
        return _load_from_env_accounts()
    path = _resolve_config_path()
    return _load_from_file(path)
