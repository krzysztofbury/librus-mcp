#!/usr/bin/env python3
"""Install a wheel outside the checkout and verify its MCP stdio identity."""

import argparse
import json
import os
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any

HANDSHAKE_TIMEOUT_SECONDS = 30


class VerificationError(RuntimeError):
    """The built wheel did not pass release verification."""


def read_project_version(project_file: Path) -> str:
    with project_file.open("rb") as file:
        project = tomllib.load(file).get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise VerificationError(f"project.version is missing from {project_file}")
    return project["version"]


def resolve_wheel(path: Path) -> Path:
    """Resolve a wheel file or a directory containing exactly one wheel."""
    path = path.resolve()
    if path.is_dir():
        wheels = sorted(path.glob("*.whl"))
        if len(wheels) != 1:
            raise VerificationError(f"expected exactly one wheel in {path}, found {len(wheels)}")
        path = wheels[0].resolve()
    if not path.is_file() or path.suffix != ".whl":
        raise VerificationError(f"wheel does not exist: {path}")
    return path


def parse_initialize_response(stdout: str) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise VerificationError(f"server wrote non-JSON data to stdout: {line!r}") from error
        if not isinstance(message, dict):
            raise VerificationError("server wrote a non-object JSON-RPC message")
        messages.append(message)
    responses = [message for message in messages if message.get("id") == 1]
    if len(responses) != 1:
        raise VerificationError(f"expected one initialize response, received {len(responses)}")
    return responses[0]


def synthetic_environment(temporary_directory: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith("LIBRUS_") or name in {"PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"}:
            environment.pop(name)
    environment.update(
        {
            "LIBRUS_ACCOUNTS": json.dumps(
                [{"alias": "release-smoke", "username": "synthetic", "password": "synthetic"}]
            ),
            "LIBRUS_FEATURES": json.dumps(
                {
                    "notifications": False,
                    "attachments": False,
                    "behaviour_notes": False,
                    "send_message": False,
                }
            ),
            "LIBRUS_STATE_DIR": str(temporary_directory / "state"),
            "LIBRUS_DOWNLOAD_DIR": str(temporary_directory / "downloads"),
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1",
            "NO_PROXY": "",
        }
    )
    return environment


def run_handshake(executable: Path, working_directory: Path, expected_version: str) -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "release-verifier", "version": "1"},
        },
    }
    process = subprocess.Popen(
        [str(executable)],
        cwd=working_directory,
        env=synthetic_environment(working_directory),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(
            json.dumps(request, separators=(",", ":")) + "\n",
            timeout=HANDSHAKE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise VerificationError("MCP initialize handshake timed out") from None
    if process.returncode != 0:
        raise VerificationError(f"installed server exited with code {process.returncode}: {stderr}")

    response = parse_initialize_response(stdout)
    if "error" in response:
        raise VerificationError(f"initialize returned an error: {response['error']}")
    if response.get("jsonrpc") != "2.0" or not isinstance(response.get("result"), dict):
        raise VerificationError("initialize returned an invalid JSON-RPC result")
    server_info = response["result"].get("serverInfo")
    if not isinstance(server_info, dict):
        raise VerificationError("initialize result is missing serverInfo")
    if server_info.get("name") != "librus-mcp":
        raise VerificationError(f"unexpected server name: {server_info.get('name')!r}")
    if server_info.get("version") != expected_version:
        raise VerificationError(f"unexpected server version: {server_info.get('version')!r}")


def run_cli_checks(executable: Path, working_directory: Path, expected_version: str) -> None:
    credentials = working_directory / "secrets.json"
    username = "release-cli-private-user"
    password = "release-cli-private-password"  # pragma: allowlist secret
    credentials.write_text(
        json.dumps(
            {"accounts": [{"alias": "release-smoke", "username": username, "password": password}]}
        ),
        encoding="utf-8",
    )
    if os.name == "posix":
        credentials.chmod(0o600)
    commands = [
        (["--version"], f"librus-mcp {expected_version}"),
        (["--config", str(credentials), "--check-config"], "[OK] Configuration is valid."),
        (["--config", str(credentials), "doctor"], "Result: all local checks passed."),
    ]
    for arguments, expected_output in commands:
        environment = synthetic_environment(working_directory)
        if arguments[-1] == "doctor":
            environment["LIBRUS_FEATURES"] = json.dumps(
                {"notifications": True, "attachments": True}
            )
        result = subprocess.run(
            [str(executable), *arguments],
            cwd=working_directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=HANDSHAKE_TIMEOUT_SECONDS,
            check=False,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0:
            raise VerificationError(f"installed CLI exited with code {result.returncode}: {output}")
        if expected_output not in result.stdout:
            raise VerificationError(f"installed CLI output is missing {expected_output!r}")
        if arguments[-1] == "doctor" and not all(
            marker in result.stdout
            for marker in (
                "[OK] Notification storage is ready.",
                "[OK] Attachment storage is ready.",
            )
        ):
            raise VerificationError("installed doctor did not verify local storage")
        if username in output or password in output or "Traceback" in output:
            raise VerificationError("installed CLI exposed private data or a traceback")


def verify_wheel(repository: Path, wheel: Path) -> None:
    wheel = resolve_wheel(wheel)
    expected_version = read_project_version(repository / "pyproject.toml")
    with tempfile.TemporaryDirectory(prefix="librus-mcp-release-") as temporary_name:
        temporary_directory = Path(temporary_name).resolve()
        if temporary_directory == repository or repository in temporary_directory.parents:
            raise VerificationError("temporary environment must be outside the checkout")
        virtual_environment = temporary_directory / "venv"
        subprocess.run(
            ["uv", "venv", "--python", "3.14", str(virtual_environment)],
            cwd=temporary_directory,
            check=True,
        )
        python = virtual_environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        requirements = temporary_directory / "runtime-requirements.txt"
        subprocess.run(
            [
                "uv",
                "export",
                "--frozen",
                "--no-dev",
                "--no-emit-project",
                "--format",
                "requirements.txt",
                "--output-file",
                str(requirements),
            ],
            cwd=repository,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--require-hashes",
                "--requirements",
                str(requirements),
            ],
            cwd=temporary_directory,
            check=True,
        )
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
            cwd=temporary_directory,
            check=True,
        )
        executable = virtual_environment / (
            "Scripts/librus-mcp.exe" if os.name == "nt" else "bin/librus-mcp"
        )
        run_cli_checks(executable, temporary_directory, expected_version)
        run_handshake(executable, temporary_directory, expected_version)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "wheel", type=Path, help="a built wheel or directory containing exactly one wheel"
    )
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    try:
        verify_wheel(repository, arguments.wheel)
    except (OSError, subprocess.CalledProcessError, VerificationError) as error:
        raise SystemExit(f"wheel verification failed: {error}") from None
    print("verified installed wheel MCP identity")


if __name__ == "__main__":
    main()
