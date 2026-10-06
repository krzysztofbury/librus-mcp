"""CLI for the native 2.0 development line; never import the old server."""

import argparse
import asyncio
import json
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path

from librus_mcp import __version__
from librus_mcp.config import ConfigError, load_config


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="librus-mcp")
    parser.add_argument("--version", action="version", version=f"librus-mcp {__version__}")
    parser.add_argument("--config", type=Path, help="explicit private configuration file")
    parser.add_argument(
        "--check-config", action="store_true", help="validate without network or writes"
    )
    parser.add_argument(
        "--doctor", action="store_true", help="offline configuration/feature diagnostics"
    )
    parser.add_argument(
        "--doctor-storage",
        action="store_true",
        help="with --doctor, explicitly exercise disposable native SQLite stores",
    )
    parser.add_argument(
        "--generate-context-key",
        action="store_true",
        help="print a new key; save it privately once",
    )
    commands = parser.add_subparsers(dest="command")
    migration = commands.add_parser(
        "migrate-state", help="offline legacy inventory/bootstrap; never overwrites source"
    )
    mode = migration.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    migration.add_argument("--source-dir", type=Path, required=True)
    migration.add_argument("--account-alias", required=True)
    migration.add_argument("--mapping-file", type=Path)
    migration.add_argument("--confirm-writers-stopped", action="store_true")
    migration.add_argument("--confirm-login-binding-reviewed", action="store_true")
    recovery = commands.add_parser(
        "notification-state", help="offline native recovery/export; not a downgrade"
    )
    recovery.add_argument("--account-alias", required=True)
    recovery_mode = recovery.add_mutually_exclusive_group(required=True)
    recovery_mode.add_argument("--status", action="store_true")
    recovery_mode.add_argument("--export-file", type=Path)
    recovery_mode.add_argument("--resolve-uncertain-consume", action="store_true")
    recovery.add_argument("--accept-possible-loss", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.generate_context_key:
        if (
            arguments.config
            or arguments.check_config
            or arguments.command
            or arguments.doctor
            or arguments.doctor_storage
        ):
            parser.error("--generate-context-key cannot be combined with configuration options")
        print(secrets.token_hex(32))
        return
    if arguments.doctor_storage and not arguments.doctor:
        parser.error("--doctor-storage requires --doctor")
    if arguments.doctor and (arguments.command or arguments.check_config):
        parser.error("--doctor cannot be combined with --check-config or an operator command")
    try:
        config = load_config(arguments.config)
    except ConfigError as error:
        print(f"librus-mcp: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    if arguments.check_config:
        if arguments.command:
            parser.error("--check-config cannot be combined with an operator command")
        print("[OK] Configuration is valid.")
        if config.context_key is None:
            print("A persistent context key will be created in the state directory on start.")
        return
    if arguments.doctor:
        from librus_python_api.exceptions import LibrusError

        from librus_mcp.doctor import diagnose

        try:
            report = asyncio.run(diagnose(config, check_storage=arguments.doctor_storage))
        except ConfigError as error:
            print(f"librus-mcp: {error}", file=sys.stderr)
            raise SystemExit(1) from None
        except LibrusError as error:
            print(f"librus-mcp: doctor failed ({error.kind.value.upper()})", file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(report, separators=(",", ":")))
        return
    if arguments.command in {"migrate-state", "notification-state"}:
        from librus_python_api.exceptions import LibrusError

        from librus_mcp.context_key import provision_context_key
        from librus_mcp.migration import migrate_state, notification_state

        try:
            # Operator commands bind the same persistent key that serving uses.
            config = asyncio.run(provision_context_key(config))
            if arguments.command == "migrate-state":
                report = asyncio.run(
                    migrate_state(
                        config,
                        source_dir=arguments.source_dir,
                        account_alias=arguments.account_alias,
                        mapping_file=arguments.mapping_file,
                        apply=arguments.apply,
                        writers_stopped=arguments.confirm_writers_stopped,
                        binding_reviewed=arguments.confirm_login_binding_reviewed,
                    )
                )
            else:
                if arguments.accept_possible_loss and not arguments.resolve_uncertain_consume:
                    parser.error("--accept-possible-loss requires --resolve-uncertain-consume")
                report = asyncio.run(
                    notification_state(
                        config,
                        account_alias=arguments.account_alias,
                        export_file=arguments.export_file,
                        resolve_uncertain=arguments.resolve_uncertain_consume,
                        accept_possible_loss=arguments.accept_possible_loss,
                    )
                )
        except ConfigError as error:
            print(f"librus-mcp: {error}", file=sys.stderr)
            raise SystemExit(1) from None
        except LibrusError as error:
            print(
                f"librus-mcp: migration failed ({error.kind.value.upper()}); originals retained",
                file=sys.stderr,
            )
            raise SystemExit(1) from None
        print(json.dumps(report, separators=(",", ":")))
        return
    from librus_python_api.exceptions import LibrusError

    from librus_mcp.runtime import prepare_runtime
    from librus_mcp.server import create_server

    # Fail before the protocol starts with one actionable line, not a lifespan
    # traceback. The lifespan repeats this idempotent preparation.
    try:
        config = asyncio.run(prepare_runtime(config))
    except ConfigError as error:
        print(f"librus-mcp: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except LibrusError as error:
        print(
            f"librus-mcp: cannot prepare private state/download directories "
            f"({error.kind.value.upper()}); they must be directories owned by the "
            "current user on a local disk",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    create_server(config).run(transport="stdio")


if __name__ == "__main__":
    main()
