#!/usr/bin/env python3
"""Verify a container image as users run it, without contacting Librus.

Checks the registry ownership label and version, that no historical references
or tests were copied in, a stdio session from a read-only multi-login file, and
the HTTP transport, as the image user with a named volume, refusing requests
without the bearer token or with an unlisted Host and serving the environment
login with the token.
"""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import anyio
import httpx2
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

# Direct script execution puts this directory, not the repository root, on sys.path.
sys.path.append(str(Path(__file__).resolve().parents[1]))
from release_verification.verify_release import (  # noqa: E402
    VerificationError,
    read_project_version,
)

ROOT = Path(__file__).resolve().parents[1]
STARTUP_TIMEOUT_SECONDS = 60
ACCOUNTS = [
    {
        "alias": "first",
        "username": "fixture-1",
        "password": "fixture-only",  # pragma: allowlist secret - fixture only
    },
    {
        "alias": "second",
        "username": "fixture-2",
        "password": "fixture-only",  # pragma: allowlist secret - fixture only
    },
]


def docker(*arguments: str) -> str:
    return subprocess.run(
        ["docker", *arguments], check=True, capture_output=True, text=True
    ).stdout.strip()


def check_identity(image: str, version: str) -> None:
    name = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))["name"]
    label = docker(
        "image",
        "inspect",
        image,
        "--format",
        '{{index .Config.Labels "io.modelcontextprotocol.server.name"}}',
    )
    if label != name:
        raise VerificationError(f"image label {label!r} must equal server.json name {name!r}")
    if docker("run", "--rm", image, "--version") != f"librus-mcp {version}":
        raise VerificationError(f"image does not run librus-mcp {version}")
    if docker("image", "inspect", image, "--format", "{{.Config.User}}") in {"", "0", "root"}:
        raise VerificationError("image must run as an unprivileged user")
    # Root only for this listing, so no unreadable directory hides a match.
    found = docker(
        "run",
        "--rm",
        "--user",
        "0",
        "--entrypoint",
        "find",
        image,
        "/",
        "-xdev",
        "(",
        "-path",
        "*legacy_reference*",
        "-o",
        "-name",
        "tests_native",
        ")",
        "-print",
        "-quit",
    )
    if found:
        raise VerificationError(f"image contains excluded source: {found}")


async def check_stdio(image: str, directory: Path) -> None:
    config = directory / "config.json"
    config.write_text(json.dumps({"accounts": ACCOUNTS}), encoding="utf-8")
    config.chmod(0o600)
    data = directory / "data"
    data.mkdir()
    parameters = StdioServerParameters(
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-v",
            f"{data}:/data",
            "-v",
            f"{config}:/config/config.json:ro",
            "-e",
            "LIBRUS_CONFIG=/config/config.json",
            image,
        ],
    )
    with anyio.fail_after(STARTUP_TIMEOUT_SECONDS):
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("list_accounts", {})
    expected = {"items": [{"account_alias": account["alias"]} for account in ACCOUNTS]}
    if result.structured_content != expected:
        raise VerificationError("stdio image did not load the mounted multi-login file")
    if not (data / "state" / "context.key").is_file():
        raise VerificationError("stdio image did not keep its state in the /data mount")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


async def check_http(image: str) -> None:
    token = secrets.token_urlsafe(32)
    port = free_port()
    # The image's own user and listen address, with state in a fresh named volume.
    volume = docker("volume", "create")
    container = docker(
        "run",
        "-d",
        "--rm",
        "-p",
        f"127.0.0.1:{port}:8000",
        "-v",
        f"{volume}:/data",
        "-e",
        "LIBRUS_USERNAME=fixture-login",  # pragma: allowlist secret - fixture only
        "-e",
        "LIBRUS_PASSWORD=fixture-only",  # pragma: allowlist secret - fixture only
        "-e",
        f"LIBRUS_MCP_TOKEN={token}",
        image,
        "--transport",
        "http",
        "--allowed-host",
        "127.0.0.1:*",
    )
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        async with httpx2.AsyncClient(trust_env=False) as probe:
            while True:
                try:
                    refused = await probe.post(url, json={})
                    break
                except httpx2.TransportError:
                    if time.monotonic() > deadline:
                        raise VerificationError("HTTP image did not start") from None
                    await anyio.sleep(0.2)
            if refused.status_code != 401 or refused.headers.get("www-authenticate") != "Bearer":
                raise VerificationError("HTTP image served a request without the bearer token")
            rebound = await probe.post(
                url,
                json={},
                headers={"Authorization": f"Bearer {token}", "Host": "unlisted.example"},
            )
            if rebound.status_code != 421:
                raise VerificationError("HTTP image accepted a Host outside --allowed-host")
        client = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=STARTUP_TIMEOUT_SECONDS,
            trust_env=False,
        )
        with anyio.fail_after(STARTUP_TIMEOUT_SECONDS):
            async with client, streamable_http_client(url, http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    result = await session.call_tool("list_accounts", {})
        if result.structured_content != {"items": [{"account_alias": "librus"}]}:
            raise VerificationError("HTTP image did not load the environment login")
    finally:
        # rm -f returns once the container is gone, so the volume is free.
        subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)
        subprocess.run(["docker", "volume", "rm", volume], check=False, capture_output=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="local image reference, for example librus-mcp:dev")
    arguments = parser.parse_args()
    version = read_project_version(ROOT / "pyproject.toml")
    try:
        check_identity(arguments.image, version)
        with tempfile.TemporaryDirectory() as temporary:
            anyio.run(check_stdio, arguments.image, Path(temporary).resolve())
        anyio.run(check_http, arguments.image)
    except (VerificationError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"image verification failed: {error}") from None
    print(f"verified image {arguments.image}: librus-mcp {version}, stdio and HTTP")


if __name__ == "__main__":
    main()
