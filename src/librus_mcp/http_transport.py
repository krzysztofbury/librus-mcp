"""Self-hosted streamable HTTP: a bearer token on every request, stateless sessions.

HTTP mode is for running the server on the operator's own machine or network. It
has no TLS; put it behind a reverse proxy or a private network such as a VPN.
One token grants every configured account, so one deployment serves one trusted
operator.
"""

import hmac
import logging
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

from librus_mcp.config import AppConfig, ConfigError, notice, read_private_file

TOKEN_PATTERN = re.compile(rb"[\x21-\x7e]{32,512}")
MAX_REQUEST_BODY_BYTES = 1024 * 1024
MAX_CONCURRENT_CONNECTIONS = 32
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
UNAUTHORIZED_BODY = b'{"error":{"code":"UNAUTHORIZED"}}'


def load_token() -> bytes:
    """The bearer token from LIBRUS_MCP_TOKEN or the private LIBRUS_MCP_TOKEN_FILE."""
    if "LIBRUS_MCP_TOKEN" in os.environ and "LIBRUS_MCP_TOKEN_FILE" in os.environ:
        raise ConfigError("choose LIBRUS_MCP_TOKEN or LIBRUS_MCP_TOKEN_FILE, not both")
    if "LIBRUS_MCP_TOKEN_FILE" in os.environ:
        path = Path(os.environ["LIBRUS_MCP_TOKEN_FILE"]).expanduser()
        try:
            # A trailing newline from an editor or `echo` (CRLF on Windows) is
            # not part of the token.
            token = (
                read_private_file(path, maximum=1024, label="token file")
                .removesuffix(b"\n")
                .removesuffix(b"\r")
            )
        except ConfigError as error:
            raise ConfigError(f"LIBRUS_MCP_TOKEN_FILE: {error}") from None
    elif "LIBRUS_MCP_TOKEN" in os.environ:
        token = os.environ["LIBRUS_MCP_TOKEN"].encode("utf-8", "replace")
    else:
        raise ConfigError(
            "HTTP transport requires LIBRUS_MCP_TOKEN or LIBRUS_MCP_TOKEN_FILE; "
            "create one with --generate-token"
        )
    if TOKEN_PATTERN.fullmatch(token) is None:
        raise ConfigError(
            "the HTTP token must be 32 to 512 printable ASCII characters without spaces"
        )
    return token


class BearerTokenMiddleware:
    """Refuse every HTTP request without exactly one matching bearer token.

    ASGI lifespan events pass through: they start the server runtime.
    """

    def __init__(self, app: ASGIApp, token: bytes) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            # The MCP app serves no WebSocket route; refuse rather than route it.
            await send({"type": "websocket.close", "code": 1008})
            return
        if self._authorized(scope["headers"]):
            await self.app(scope, receive, send)
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(UNAUTHORIZED_BODY)).encode()),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": UNAUTHORIZED_BODY})

    def _authorized(self, headers: Sequence[tuple[bytes, bytes]]) -> bool:
        values = [value for name, value in headers if name.lower() == b"authorization"]
        if len(values) != 1:
            return False
        scheme, _, credential = values[0].partition(b" ")
        # Compare bytes: str comparison raises on non-ASCII input.
        return scheme.lower() == b"bearer" and hmac.compare_digest(credential, self.token)


def transport_security(host: str, allowed_hosts: Sequence[str]) -> TransportSecuritySettings | None:
    """Host and Origin checks; the SDK applies its loopback defaults when None."""
    if allowed_hosts:
        # The SDK matches HOST:* only with an explicit port, but HTTPS clients and
        # proxies send the bare name for the default port.
        hosts = list(
            dict.fromkeys(
                name for entry in allowed_hosts for name in (entry, entry.removesuffix(":*"))
            )
        )
        # No browser origin is expected: MCP clients send no Origin header.
        return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=[])
    if host not in LOOPBACK_HOSTS:
        notice(
            "Host header checks are off; pass --allowed-host with the name clients use "
            "(the bearer token still protects every request)"
        )
    return None


def serve_http(
    server: MCPServer[Any],
    config: AppConfig,
    *,
    host: str,
    port: int,
    token: bytes,
    allowed_hosts: Sequence[str] = (),
) -> None:
    import uvicorn

    if config.features.send_message:
        notice(
            "send_message is enabled over HTTP: anyone holding the token can confirm a "
            "send preview, and remote agents often run without a person approving it"
        )
    app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=MAX_REQUEST_BODY_BYTES,
        transport_security=transport_security(host, allowed_hosts),
        host=host,
    )
    # The SDK logs every stateless request at INFO; operators need warnings only.
    logging.getLogger("mcp").setLevel(logging.WARNING)
    notice(f"serving MCP over HTTP at http://{host}:{port}/mcp; requests need the bearer token")
    uvicorn.run(
        BearerTokenMiddleware(app, token),
        host=host,
        port=port,
        lifespan="on",
        server_header=False,
        limit_concurrency=MAX_CONCURRENT_CONNECTIONS,
        access_log=False,
        log_level="warning",
    )
