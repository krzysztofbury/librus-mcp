"""Self-hosted streamable HTTP: bearer token on every request, real runtime behind it."""

import os
import socket
import sys

import anyio
import httpx2
import pytest
from mcp.client import ClientSession
from mcp.client.streamable_http import streamable_http_client

from librus_mcp.cli import main
from librus_mcp.config import ConfigError
from librus_mcp.http_transport import BearerTokenMiddleware, load_token
from tests_native.test_native_stdio import REPOSITORY, server_process
from tests_native.wire import Wire

TOKEN = "fixture-token-" + "x" * 32  # pragma: allowlist secret - fixture only


@pytest.fixture(autouse=True)
def no_token_environment(monkeypatch):
    for name in ("LIBRUS_MCP_TOKEN", "LIBRUS_MCP_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)


async def call(middleware, scope):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


@pytest.mark.parametrize(
    ("headers", "allowed"),
    [
        ([], False),
        ([(b"authorization", b"Bearer wrong")], False),
        ([(b"authorization", TOKEN.encode())], False),
        ([(b"authorization", b"Basic " + TOKEN.encode())], False),
        ([(b"authorization", "Bearer żółw".encode())], False),
        ([(b"authorization", b"Bearer " + TOKEN.encode())] * 2, False),
        ([(b"authorization", b"Bearer " + TOKEN.encode())], True),
        ([(b"Authorization", b"bearer " + TOKEN.encode())], True),
    ],
)
@pytest.mark.parametrize("method", ["POST", "GET", "OPTIONS"])
@pytest.mark.asyncio
async def test_only_one_matching_bearer_token_reaches_the_server(headers, allowed, method):
    reached = []

    async def app(scope, receive, send):
        reached.append(scope["type"])

    middleware = BearerTokenMiddleware(app, TOKEN.encode())
    sent = await call(middleware, {"type": "http", "method": method, "headers": headers})
    assert reached == (["http"] if allowed else [])
    if not allowed:
        start, body = sent
        assert start["status"] == 401 and (b"www-authenticate", b"Bearer") in start["headers"]
        assert TOKEN.encode() not in body["body"]
    # Lifespan starts the runtime and must never need a token.
    await call(middleware, {"type": "lifespan"})
    assert reached[-1] == "lifespan"


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({}, "requires LIBRUS_MCP_TOKEN"),
        ({"LIBRUS_MCP_TOKEN": "short"}, "32 to 512"),
        ({"LIBRUS_MCP_TOKEN": TOKEN[:20] + " " + TOKEN[20:]}, "without spaces"),
        ({"LIBRUS_MCP_TOKEN": TOKEN + "ż"}, "printable ASCII"),
        ({"LIBRUS_MCP_TOKEN": TOKEN, "LIBRUS_MCP_TOKEN_FILE": "token"}, "not both"),
    ],
)
def test_http_token_fails_closed(environment, message, monkeypatch):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError, match=message):
        load_token()


def test_http_token_file_is_private_and_ignores_a_trailing_newline(tmp_path, monkeypatch):
    path = tmp_path / "token"
    path.write_text(TOKEN + "\n")
    path.chmod(0o600)
    if os.name == "nt":
        from tests_native.test_config import set_windows_acl

        set_windows_acl(path)
    monkeypatch.setenv("LIBRUS_MCP_TOKEN_FILE", str(path))
    assert load_token() == TOKEN.encode()
    path.unlink()
    with pytest.raises(ConfigError, match="LIBRUS_MCP_TOKEN_FILE"):
        load_token()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--generate-token", "--transport", "http"],
        ["--generate-token", "--generate-context-key"],
        ["--check-config", "--transport", "http"],
        ["--doctor", "--transport", "http"],
        ["--host", "0.0.0.0"],
        ["--transport", "http", "--port", "0"],
    ],
)
def test_transport_options_apply_only_to_serving(arguments, capsys):
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_http_serving_refuses_to_start_without_a_token(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LIBRUS_USERNAME", "fixture-login")
    monkeypatch.setenv("LIBRUS_PASSWORD", "fixture-only")  # pragma: allowlist secret
    monkeypatch.setenv("LIBRUS_STATE_DIR", str(tmp_path / "state"))
    with pytest.raises(SystemExit) as error:
        main(["--transport", "http"])
    assert error.value.code == 1
    assert "requires LIBRUS_MCP_TOKEN" in capsys.readouterr().err
    assert not (tmp_path / "state").exists()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.asyncio
async def test_http_serves_every_login_with_the_token_and_nothing_without(tmp_path):
    accounts = [("first", "login-1"), ("second", "login-2")]
    port = free_port()
    async with Wire().serve() as wire:
        parameters = server_process(
            wire.origin,
            accounts,
            state_dir=tmp_path / "state",
            serve="from librus_mcp.http_transport import serve_http\n"
            f"serve_http(server, load_config(), host='127.0.0.1', port={port}, "
            f"token={TOKEN.encode()!r})",
        )
        script = parameters.args[1]
        url = f"http://127.0.0.1:{port}/mcp"
        async with await anyio.open_process(
            [sys.executable, "-c", script], cwd=REPOSITORY, env=parameters.env
        ) as process:
            try:
                with anyio.fail_after(30):
                    # The consumer suite points proxy variables at a dead port.
                    async with httpx2.AsyncClient(trust_env=False) as probe:
                        while True:
                            try:
                                refused = await probe.post(url, json={})
                                break
                            except httpx2.TransportError:
                                await anyio.sleep(0.1)
                assert refused.status_code == 401
                assert wire.calls == []
                client = httpx2.AsyncClient(
                    headers={"Authorization": f"Bearer {TOKEN}"}, timeout=30, trust_env=False
                )
                with anyio.fail_after(30):
                    async with client, streamable_http_client(url, http_client=client) as streams:
                        async with ClientSession(*streams[:2]) as session:
                            await session.initialize()
                            assert len((await session.list_tools()).tools) == 31
                            listed = await session.call_tool("list_accounts", {})
                            assert listed.structured_content == {
                                "items": [{"account_alias": alias} for alias, _ in accounts]
                            }
                            for alias, login in accounts:
                                grades = await session.call_tool(
                                    "get_grades", {"account_alias": alias, "scope": "week"}
                                )
                                assert not grades.is_error, grades
                                assert grades.structured_content["items"][0]["raw"] == "4+"
                assert wire.logins == {login: 1 for _, login in accounts}
            finally:
                process.terminate()
