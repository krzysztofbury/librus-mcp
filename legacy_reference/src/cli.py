"""End-user command line entry point for Librus MCP."""

import argparse
import asyncio
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from src import __version__
from src.config import AppConfig, ConfigError, load_config
from src.notification_state import verify_notification_state_storage


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="librus-mcp",
        description="Connect an AI assistant to Librus and diagnose local setup problems.",
        epilog="Run without options to start the MCP server used by your AI assistant.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help="use this credentials file instead of searching or reading LIBRUS_ACCOUNTS",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate configuration without signing in to Librus",
    )
    commands = parser.add_subparsers(dest="command")
    doctor = commands.add_parser(
        "doctor",
        help="check configuration and local storage without changing school data",
    )
    doctor.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="use this credentials file",
    )
    doctor.add_argument(
        "--live",
        action="store_true",
        help="also sign in and perform one read-only check for every account",
    )
    return parser


def _account_summary(count: int) -> str:
    return f"{count} account{'s' if count != 1 else ''} configured"


def _run_config_check(config_path: Path | None) -> int:
    try:
        config = load_config(config_path)
    except ConfigError as error:
        print("[FAIL] Configuration is not ready.", file=sys.stderr)
        print(f"Reason: {error}", file=sys.stderr)
        print(
            "Next step: correct the credentials file or MCP environment, then rerun "
            "this same command.",
            file=sys.stderr,
        )
        return 2
    print("[OK] Configuration is valid.")
    print(f"[OK] {_account_summary(len(config.accounts))}.")
    print("Next step: reconnect your AI assistant and ask it to list configured students.")
    return 0


def _prepare_download_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("download path is not a directory")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".librus-mcp-doctor-", dir=path)
    temporary_path = Path(temporary_name)
    linked_path = temporary_path.with_name(f"{temporary_path.name}.link")
    linked = False
    try:
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary_path, linked_path, follow_symlinks=False)
        linked = True
    finally:
        primary_error = sys.exception()
        cleanup_error: OSError | None = None
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError as error:
                cleanup_error = error
        if linked:
            try:
                linked_path.unlink(missing_ok=True)
            except OSError as error:
                cleanup_error = cleanup_error or error
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError as error:
            cleanup_error = cleanup_error or error
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


def _check_local_storage(config: AppConfig) -> bool:
    healthy = True
    if config.features.notifications:
        try:
            verify_notification_state_storage(config.state_dir)
        except OSError, RuntimeError, ValueError:
            healthy = False
            print("[FAIL] Notification storage is not ready.")
            print("       Choose a state folder inside your user profile and try again.")
        else:
            print("[OK] Notification storage is ready.")
    else:
        print("[SKIP] Notification storage is disabled in configuration.")
    if config.features.attachments:
        try:
            _prepare_download_directory(config.download_dir)
        except OSError, ValueError:
            healthy = False
            print("[FAIL] Attachment storage is not ready.")
            print("       Choose a download folder inside your user profile and try again.")
        else:
            print("[OK] Attachment storage is ready.")
    else:
        print("[SKIP] Attachment storage is disabled in configuration.")
    return healthy


async def _check_live_accounts(config: AppConfig) -> bool:
    from src.librus_client import LibrusManager

    LibrusManager._config_cache = config
    healthy = True
    for account in config.accounts:
        try:
            await LibrusManager.check_account_connection(account.alias)
        except Exception:  # noqa: BLE001 - the diagnostic boundary must never leak a traceback
            healthy = False
            print(f"[FAIL] Librus account '{account.alias}': sign-in or read access failed.")
            print("       Check the credentials and internet connection, then try again.")
        else:
            print(f"[OK] Librus account '{account.alias}': sign-in and read access work.")
    return healthy


def _run_doctor(live: bool, config_path: Path | None) -> int:
    print(f"Librus MCP doctor (version {__version__})")
    print("This command never changes grades, messages, attendance, or other school data.")
    try:
        config = load_config(config_path)
    except ConfigError as error:
        print("[FAIL] Configuration is not ready.")
        print(f"Reason: {error}")
        print("Next step: fix the configuration, then rerun this same command.")
        return 2
    print(f"[OK] Configuration: {_account_summary(len(config.accounts))}.")
    if not _check_local_storage(config):
        print("Result: local setup needs attention. No Librus connection was attempted.")
        return 1
    if not live:
        print("[SKIP] Live Librus checks were not requested.")
        print("For sign-in and read checks, run: librus-mcp doctor --live")
        print("Result: all local checks passed.")
        return 0
    print("Live mode contacts Librus and performs read-only checks for every account.")
    if not asyncio.run(_check_live_accounts(config)):
        print("Result: one or more live checks need attention.")
        return 1
    print("Result: all local and live checks passed.")
    return 0


def _run_server(config_path: Path | None) -> None:
    if config_path is not None:
        try:
            config = load_config(config_path)
        except ConfigError as error:
            print(f"librus-mcp: configuration error: {error}", file=sys.stderr)
            raise SystemExit(2) from None
        from src.librus_client import LibrusManager

        LibrusManager._config_cache = config
    from src.server import main as run_server

    run_server()


def main(argv: Sequence[str] | None = None) -> None:
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.check_config and arguments.command is not None:
        parser.error("--check-config cannot be combined with another command")
    if arguments.check_config:
        exit_code = _run_config_check(arguments.config)
    elif arguments.command == "doctor":
        exit_code = _run_doctor(arguments.live, arguments.config)
    else:
        _run_server(arguments.config)
        return
    if exit_code != 0:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
