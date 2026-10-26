"""CLI for the native 2.0 development line; never import the old server."""

import argparse
import asyncio
import json
import os
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
    parser.add_argument(
        "--generate-token",
        action="store_true",
        help="print a new HTTP bearer token; save it privately once",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio for a local assistant (default); http to self-host on your own network",
    )
    parser.add_argument(
        "--host",
        help="HTTP listen address (default LIBRUS_MCP_HOST, else 127.0.0.1; "
        "the container image sets 0.0.0.0)",
    )
    parser.add_argument("--port", type=int, help="HTTP listen port (default 8000)")
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        metavar="HOST[:PORT]",
        help="Host header clients use, repeatable; HOST:* allows HOST with any port or none",
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
    http_options = (
        arguments.host is not None or arguments.port is not None or arguments.allowed_host
    )
    serving_options = arguments.transport != "stdio" or http_options
    generator = (
        "--generate-context-key"
        if arguments.generate_context_key
        else "--generate-token"
        if arguments.generate_token
        else None
    )
    if generator is not None:
        if (
            arguments.config
            or arguments.check_config
            or arguments.command
            or arguments.doctor
            or arguments.doctor_storage
            or (arguments.generate_context_key and arguments.generate_token)
            or serving_options
        ):
            parser.error(f"{generator} cannot be combined with other options")
        print(
            secrets.token_hex(32) if arguments.generate_context_key else secrets.token_urlsafe(32)
        )
        return
    if serving_options and (arguments.check_config or arguments.doctor or arguments.command):
        parser.error("transport options apply only to serving")
    if http_options and arguments.transport != "http":
        parser.error("--host, --port and --allowed-host require --transport http")
    if arguments.port is not None and not 1 <= arguments.port <= 65535:
        parser.error("--port must be between 1 and 65535")
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

    token = b""
    if arguments.transport == "http":
        from librus_mcp.http_transport import load_token

        try:
            token = load_token()
        except ConfigError as error:
            print(f"librus-mcp: {error}", file=sys.stderr)
            raise SystemExit(1) from None
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
    if arguments.transport == "http":
        from librus_mcp.http_transport import serve_http

        serve_http(
            create_server(config),
            config,
            host=arguments.host or os.environ.get("LIBRUS_MCP_HOST") or "127.0.0.1",
            port=arguments.port or 8000,
            token=token,
            allowed_hosts=arguments.allowed_host,
        )
        return
    create_server(config).run(transport="stdio")


if __name__ == "__main__":
    main()
