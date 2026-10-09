#!/usr/bin/env python3
"""Install a wheel outside the checkout and verify its MCP stdio identity."""

import argparse
import asyncio
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import anyio
from jsonschema.validators import validator_for
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

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


def synthetic_environment(
    temporary_directory: Path, *, all_features: bool = False
) -> dict[str, str]:
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith("LIBRUS_") or name in {"PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"}:
            environment.pop(name)
    environment.update(
        {
            "LIBRUS_ACCOUNTS": json.dumps(
                [
                    {
                        "alias": "release-smoke",
                        "username": "synthetic",
                        "password": "synthetic",  # pragma: allowlist secret - fixture only
                    }
                ]
            ),
            "LIBRUS_CONTEXT_KEY": secrets.token_hex(32),
            # The default profile uses the shipped feature defaults.
            "LIBRUS_FEATURES": json.dumps({"send_message": True} if all_features else {}),
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


async def run_tool_checks(
    executable: Path, working_directory: Path, *, all_features: bool = False
) -> None:
    """Check the installed server's catalog and a credential-free tool call."""
    server = StdioServerParameters(
        command=str(executable),
        cwd=working_directory,
        env=synthetic_environment(working_directory, all_features=all_features),
    )
    try:
        with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
            async with stdio_client(server) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    catalog = await session.list_tools()
                    tools = {tool.name: tool for tool in catalog.tools}
                    if len(tools) != (35 if all_features else 31):
                        raise VerificationError(
                            "installed catalog has an unexpected feature profile"
                        )
                    for tool in catalog.tools:
                        validator_for(tool.input_schema).check_schema(tool.input_schema)
                        if tool.output_schema is None:
                            raise VerificationError("installed tool has no output schema")
                        validator_for(tool.output_schema).check_schema(tool.output_schema)
                    if (
                        len(catalog.model_dump_json(by_alias=True, exclude_unset=True).encode())
                        > (144 if all_features else 128) * 1024
                    ):
                        raise VerificationError("installed catalog exceeds its context budget")
                    grades_tool = tools.get("get_grades")
                    if grades_tool is None or grades_tool.output_schema is None:
                        raise VerificationError("installed get_grades has no output schema")
                    result = await session.call_tool("list_accounts", {})
                    if result.is_error or result.structured_content != {
                        "items": [{"account_alias": "release-smoke"}]
                    }:
                        raise VerificationError(
                            "installed list_accounts returned an invalid result"
                        )
    except Exception as error:  # noqa: BLE001 - redact SDK and subprocess failures at this boundary
        raise VerificationError(
            f"installed MCP tool check failed: {type(error).__name__}"
        ) from None


def run_cli_checks(executable: Path, working_directory: Path, expected_version: str) -> None:
    credentials = working_directory / "secrets.json"
    username = "release-cli-private-user"
    password = "release-cli-private-password"  # pragma: allowlist secret
    credentials.write_text(
        json.dumps(
            {
                "accounts": [
                    {"alias": "release-smoke", "username": username, "password": password}
                ],
                "context_key": secrets.token_hex(32),
            }
        ),
        encoding="utf-8",
    )
    if os.name == "posix":
        credentials.chmod(0o600)
    elif os.name == "nt":
        import win32api
        import win32con
        import win32security

        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        finally:
            token.Close()
        acl = win32security.ACL()
        acl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.GENERIC_ALL, user)
        win32security.SetNamedSecurityInfo(
            str(credentials),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION
            | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            acl,
            None,
        )
    commands = [
        (["--version"], f"librus-mcp {expected_version}"),
        (["--config", str(credentials), "--check-config"], "[OK] Configuration is valid."),
    ]
    for arguments, expected_output in commands:
        environment = synthetic_environment(working_directory)
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
        if username in output or password in output or "Traceback" in output:
            raise VerificationError("installed CLI exposed private data or a traceback")


def run_consumer_tests(repository: Path, python: Path, working_directory: Path) -> None:
    """Run copied offline consumer tests against the installed wheel, never source."""
    requirements = working_directory / "test-requirements.txt"
    subprocess.run(
        ["uv", "export", "--frozen", "--no-emit-project", "--output-file", str(requirements)],
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
        cwd=working_directory,
        check=True,
    )
    tests = working_directory / "consumer-tests"
    tests.mkdir()
    shutil.copytree(
        repository / "tests_native",
        tests / "tests_native",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (tests / "pytest.ini").write_text(
        "[pytest]\nasyncio_mode = strict\ntestpaths = tests_native\n",
        encoding="utf-8",
    )
    subprocess.run(
        [str(python), "-m", "pytest", "-q", "--basetemp", str(working_directory / "pytest")],
        cwd=tests,
        env={
            key: value
            for key, value in synthetic_environment(working_directory).items()
            if not key.startswith("LIBRUS_")
        },
        # Hosted Windows runs the suite in ~155-165s; a whole-suite cap is a hang
        # guard, not a performance gate, so leave headroom for runner variance.
        timeout=600,
        check=True,
    )


def verify_wheel(repository: Path, wheel: Path, *, consumer_tests: bool = False) -> None:
    wheel = resolve_wheel(wheel)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if any(name.startswith("src/") for name in names):
            raise VerificationError("wheel contains the legacy src package")
        if "librus_mcp/cli.py" not in names:
            raise VerificationError("wheel is missing the native entry point")
        for name in names:
            if "legacy_reference/" in name or name.startswith("tests/"):
                raise VerificationError("wheel contains historical source or tests")
            if name.endswith(".py") or name.endswith("/METADATA"):
                body = archive.read(name)
                if b"librus_apix" in body or b"Requires-Dist: librus-apix" in body:
                    raise VerificationError("wheel contains an apix import or dependency")
            if name.endswith("/METADATA") and b"License-Expression: MIT" not in archive.read(name):
                raise VerificationError("wheel license metadata is not MIT")
        licenses = [name for name in names if name.endswith("/licenses/LICENSE")]
        if len(licenses) != 1 or not archive.read(licenses[0]).startswith(
            (b"MIT License\n", b"MIT License\r\n")
        ):
            raise VerificationError("wheel license notice is not MIT")
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
        asyncio.run(run_tool_checks(executable, temporary_directory))
        asyncio.run(run_tool_checks(executable, temporary_directory, all_features=True))
        if consumer_tests:
            run_consumer_tests(repository, python, temporary_directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "wheel", type=Path, help="a built wheel or directory containing exactly one wheel"
    )
    parser.add_argument(
        "--consumer-tests",
        action="store_true",
        help="also run the offline consumer suite against the isolated installed wheel",
    )
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    try:
        verify_wheel(repository, arguments.wheel, consumer_tests=arguments.consumer_tests)
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        VerificationError,
    ) as error:
        raise SystemExit(f"wheel verification failed: {error}") from None
    print("verified installed wheel MCP identity")


if __name__ == "__main__":
    main()
