"""Consumer download binding, complete files and bounded inert MCP resources."""

import base64
import hashlib
import os
from pathlib import Path

import anyio
import pytest
from librus_python_api.exceptions import ErrorKind, LibrusError
from librus_python_api.files import PublishedAttachment
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError

from librus_mcp.resources import AttachmentResources
from tests_native.test_native_stdio import server_process
from tests_native.wire import Wire


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["modern", "legacy"])
async def test_native_publication_binding_resource_restart_and_failed_download(tmp_path, backend):
    async with Wire().serve() as wire:
        process = server_process(
            wire.origin,
            [("first", "71", backend), ("second", "72", backend)],
            features={"attachments": True},
            download_dir=tmp_path / "downloads",
        )
        with anyio.fail_after(30):
            async with stdio_client(process) as streams, ClientSession(*streams) as session:
                await session.initialize()
                templates = (await session.list_resource_templates()).resource_templates
                assert [item.uri_template for item in templates] == [
                    "librus-attachment://files/{token}"
                ]
                listed = await session.call_tool(
                    "get_messages", {"account_alias": "first", "limit": 1}
                )
                assert not listed.is_error
                reference = listed.structured_content["items"][0]["reference"]
                arguments = {
                    "account_alias": "first",
                    "attachment_ref": {"message": reference, "identifier": "91"},
                    "filename": "../../Fixture.bin",
                }
                calls = len(wire.calls)
                foreign = await session.call_tool(
                    "download_attachment", arguments | {"account_alias": "second"}
                )
                assert foreign.is_error and foreign.structured_content == {
                    "error": {"code": "INVALID_INPUT"}
                }
                assert len(wire.calls) == calls
                result = await session.call_tool("download_attachment", arguments)
                assert not result.is_error, result
                saved = result.structured_content
                path = Path(saved["local_path"])
                assert path.parent == tmp_path / "downloads" / "native-v2"
                assert path.read_bytes() == wire.attachment_body
                assert saved["sha256"] == hashlib.sha256(wire.attachment_body).hexdigest()
                assert "fixture-key" not in result.model_dump_json()
                assert not any(
                    route.startswith("/api/inbox/messages/") for _, route, _ in wire.calls
                )
                calls = len(wire.calls)
                uri = saved["resource_uri"]
                if os.name == "posix":
                    assert uri and saved["resource_ttl_seconds"] == 900
                    # Resources are immutable snapshots, not repeated filesystem reads.
                    path.write_bytes(b"Replacement data")
                    resource = await session.read_resource(uri)
                    assert base64.b64decode(resource.contents[0].blob) == wire.attachment_body
                    assert resource.contents[0].mime_type == "application/octet-stream"
                    with pytest.raises(MCPError):
                        await session.read_resource("librus-attachment://files/not-a-token")
                else:
                    assert uri is None
                assert len(wire.calls) == calls
                # A fresh failed stream publishes no partial or empty file.
                files = set(path.parent.iterdir())
                limited = await session.call_tool(
                    "download_attachment", arguments | {"max_bytes": 1}
                )
                assert limited.is_error and limited.structured_content == {
                    "error": {"code": "LIMIT"}
                }
                assert set(path.parent.iterdir()) == files
                wire.attachment_location = "https://example.invalid/GetFile/not-authorized"
                denied = await session.call_tool("download_attachment", arguments)
                assert denied.is_error and denied.structured_content == {
                    "error": {"code": "ACCESS_DENIED"}
                }
                assert set(path.parent.iterdir()) == files
            if uri:
                async with stdio_client(process) as streams, ClientSession(*streams) as session:
                    await session.initialize()
                    calls = len(wire.calls)
                    with pytest.raises(MCPError):
                        await session.read_resource(uri)
                    assert len(wire.calls) == calls


@pytest.mark.skipif(os.name != "posix", reason="POSIX resource snapshots")
def test_resource_capacity_expiry_and_nofollow_boundary(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("librus_mcp.resources.time.monotonic", lambda: clock[0])
    directory = tmp_path / "files"
    directory.mkdir(mode=0o700)
    path = directory / "fixture.bin"
    body = b"Inert data"
    path.write_bytes(body)
    path.chmod(0o600)
    saved = PublishedAttachment(
        path=path,
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        content_type="application/octet-stream",
    )
    resources = AttachmentResources(directory)
    uris = [resources.snapshot(saved) for _ in range(32)]
    assert all(uris) and resources.snapshot(saved) is None
    assert path.read_bytes() == body  # Capacity falls back to the complete native file.
    clock[0] += 901
    with pytest.raises(LibrusError) as expired:
        resources.read(uris[0].rsplit("/", 1)[1])
    assert expired.value.kind is ErrorKind.INVALID_INPUT
    assert resources.snapshot(saved) is not None
    outside = tmp_path / "outside.bin"
    outside.write_bytes(body)
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(LibrusError) as unsafe:
        resources.snapshot(saved)
    assert unsafe.value.kind is ErrorKind.STORAGE


@pytest.mark.asyncio
async def test_snapshot_failure_after_publication_returns_complete_local_file(tmp_path):
    setup = """from librus_mcp.resources import AttachmentResources
from librus_python_api.exceptions import LibrusError, ErrorKind
def unavailable(self, saved):
    raise LibrusError(ErrorKind.STORAGE)
AttachmentResources.snapshot = unavailable
"""
    async with Wire().serve() as wire:
        process = server_process(
            wire.origin,
            [("account", "71")],
            features={"attachments": True},
            download_dir=tmp_path / "downloads",
            setup_script=setup,
        )
        with anyio.fail_after(20):
            async with stdio_client(process) as streams, ClientSession(*streams) as session:
                await session.initialize()
                messages = await session.call_tool(
                    "get_messages", {"account_alias": "account", "limit": 1}
                )
                result = await session.call_tool(
                    "download_attachment",
                    {
                        "account_alias": "account",
                        "attachment_ref": {
                            "message": messages.structured_content["items"][0]["reference"],
                            "identifier": "91",
                        },
                        "filename": "Fixture.bin",
                    },
                )
                assert not result.is_error, result
                assert result.structured_content["resource_uri"] is None
                assert (
                    Path(result.structured_content["local_path"]).read_bytes()
                    == wire.attachment_body
                )
                assert len(list((tmp_path / "downloads" / "native-v2").iterdir())) == 1
