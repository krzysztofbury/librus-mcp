import json
import os
from typing import List
from pydantic import BaseModel

# Resolve secrets.json relative to the project root (one level up from src/).
SECRETS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "secrets.json"
)


class AccountConfig(BaseModel):
    alias: str
    username: str
    password: str


class AppConfig(BaseModel):
    accounts: List[AccountConfig]


def load_config() -> AppConfig:
    if not os.path.exists(SECRETS_FILE):
        raise FileNotFoundError(
            f"Configuration file {SECRETS_FILE} not found. "
            "Please create it based on secrets.json.template"
        )

    with open(SECRETS_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return AppConfig(**data)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON in {SECRETS_FILE}")
        except Exception as e:
            raise ValueError(f"Error loading config: {str(e)}")
