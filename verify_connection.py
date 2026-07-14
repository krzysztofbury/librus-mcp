"""Credential-gated live smoke test: authenticates the first configured
account and exercises one read tool per subsystem. Run manually with real
credentials (secrets.json or LIBRUS_ACCOUNTS); never runs in CI.

Usage:
    uv run python verify_connection.py [--all-accounts]
"""

import asyncio
import sys

from src.config import load_config
from src.librus_client import LibrusManager


async def verify_account(alias: str) -> bool:
    print(f"\nTesting connection for alias: '{alias}'...")
    try:
        await LibrusManager.get_client(alias)
        print("  [ok] Authentication successful")
    except Exception as error:
        print(f"  [FAIL] Authentication failed: {error}")
        return False

    healthy = True

    try:
        grades = await LibrusManager.fetch_grades(alias)
        semesters = len(grades["numeric"])
        print(f"  [ok] Grades fetched ({semesters} semester groups)")
    except Exception as error:
        healthy = False
        print(f"  [FAIL] Grades: {error}")

    try:
        messages = await LibrusManager.fetch_messages(alias)
        count = len(messages["messages"])
        max_page = messages["max_page"]
        print(f"  [ok] Messages fetched (page 0: {count} messages, max_page: {max_page})")
    except Exception as error:
        healthy = False
        print(f"  [FAIL] Messages: {error}")

    try:
        timetable = await LibrusManager.fetch_timetable(alias)
        print(f"  [ok] Timetable fetched ({len(timetable)} weekday columns)")
    except Exception as error:
        healthy = False
        print(f"  [FAIL] Timetable: {error}")

    return healthy


async def main() -> int:
    print("--- Verifying Librus Configuration ---")
    try:
        config = load_config()
    except Exception as error:
        print(f"[FAIL] Configuration error: {error}")
        return 1

    aliases = [account.alias for account in config.accounts]
    print(f"Found {len(aliases)} accounts: {aliases}")

    if "--all-accounts" in sys.argv:
        targets = aliases
    else:
        targets = aliases[:1]

    results = [await verify_account(alias) for alias in targets]
    if all(results):
        print("\nAll checks passed.")
        return 0
    print("\nSome checks FAILED — see above.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
