import asyncio
from src.librus_client import LibrusManager
from src.config import load_config
from src.patches import apply_patches


async def main():
    apply_patches()
    print("--- Verifying Librus Configuration ---")
    try:
        config = load_config()
        if not config.accounts:
            print("No accounts found in secrets.json")
            return

        print(f"Found {len(config.accounts)} accounts: {[acc.alias for acc in config.accounts]}")

        # Try the first account
        alias = config.accounts[0].alias
        print(f"\nTesting connection for alias: '{alias}'...")

        # Check Token (Login)
        try:
            await LibrusManager.get_client(alias)
            print("✅ Authentication successful!")
        except Exception as e:
            print(f"❌ Authentication failed: {e}")
            return

        # Check Grades
        print("Fetching grades...")
        try:
            grades = await LibrusManager.fetch_grades(alias)
            count = len(grades) if isinstance(grades, list) else len(grades.keys())
            print(f"✅ Grades fetched successfully (found items for {count} subjects/categories).")
        except Exception as e:
            import traceback

            traceback.print_exc()
            print(f"❌ Failed to fetch grades: {e}")

        # Check Messages
        print("Fetching messages...")
        try:
            msgs = await LibrusManager.fetch_messages(alias)
            received = msgs.get("received", [])
            print(f"✅ Messages fetched successfully (found {len(received)} received messages).")
        except Exception as e:
            print(f"❌ Failed to fetch messages: {e}")

    except Exception as e:
        print(f"❌ Configuration Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
