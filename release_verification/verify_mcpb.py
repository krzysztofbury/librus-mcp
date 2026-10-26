#!/usr/bin/env python3
"""Install an MCP Bundle the way a host does and verify its MCP stdio identity.

The bundle is unpacked into an empty directory, its manifest command runs with
the login passed as the host would pass user_config, and the server must start,
list its catalog and report the configured alias without contacting Librus.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import anyio
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# Direct script execution puts this directory, not the repository root, on sys.path.
sys.path.append(str(Path(__file__).resolve().parents[1]))
from release_verification.verify_release import (  # noqa: E402
    VerificationError,
    read_project_version,
)

STARTUP_TIMEOUT_SECONDS = 600
USER_CONFIG = {"username": "fixture-login", "password": "fixture-only", "alias": ""}


def resolve_bundle(path: Path) -> Path:
    """Resolve a bundle file or a directory containing exactly one bundle."""
    path = path.resolve()
    if path.is_dir():
        bundles = sorted(path.glob("*.mcpb"))
        if len(bundles) != 1:
            raise VerificationError(f"expected exactly one bundle in {path}, found {len(bundles)}")
        path = bundles[0]
    if not path.is_file() or path.suffix != ".mcpb":
        raise VerificationError(f"{path} is not an .mcpb file")
    return path


def substitute(value: str, directory: Path) -> str:
    value = value.replace("${__dirname}", str(directory))
    for key, setting in USER_CONFIG.items():
        value = value.replace("${user_config." + key + "}", setting)
    if "${" in value:
        raise VerificationError(f"unsupported manifest variable in {value!r}")
    return value


async def check_server(directory: Path, private: Path, version: str) -> int:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        raise VerificationError(f"bundle manifest version must be {version!r}")
    config = manifest["server"]["mcp_config"]
    command = shutil.which(config["command"])
    if command is None:
        raise VerificationError(f"{config['command']} is not on PATH")
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("LIBRUS_") and name not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
    }
    # Keep the server's state away from the verifying user's, in directories the
    # server creates itself, as verify_wheel does; uv keeps its usual cache.
    environment |= {
        "LIBRUS_STATE_DIR": str(private / "state"),
        "LIBRUS_DOWNLOAD_DIR": str(private / "downloads"),
    }
    environment |= {name: substitute(value, directory) for name, value in config["env"].items()}
    parameters = StdioServerParameters(
        command=command,
        args=[substitute(argument, directory) for argument in config["args"]],
        env=environment,
    )
    with anyio.fail_after(STARTUP_TIMEOUT_SECONDS):
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                if (initialized.server_info.name, initialized.server_info.version) != (
                    "librus-mcp",
                    version,
                ):
                    raise VerificationError("bundle server reported the wrong identity")
                tools = (await session.list_tools()).tools
                result = await session.call_tool("list_accounts", {})
                if result.structured_content != {"items": [{"account_alias": "librus"}]}:
                    raise VerificationError("bundle server did not load the host login")
    return len(tools)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help=".mcpb file or a directory with one")
    arguments = parser.parse_args()
    version = read_project_version(Path(__file__).resolve().parents[1] / "pyproject.toml")
    try:
        bundle = resolve_bundle(arguments.bundle)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "extension"
            with zipfile.ZipFile(bundle) as archive:
                archive.extractall(directory)
            tools = anyio.run(check_server, directory, Path(temporary), version)
    except VerificationError as error:
        raise SystemExit(f"bundle verification failed: {error}") from None
    print(f"verified bundle {bundle.name}: {tools} tools, host login loaded")


if __name__ == "__main__":
    main()
