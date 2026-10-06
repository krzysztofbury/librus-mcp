"""Opt-in native file publication and bounded MCP snapshots; no upstream URLs."""

from typing import Annotated, Any, cast

from librus_python_api import (
    MessageAttachmentReference,
    MessageReference,
    ModernMessageAttachmentReference,
    ModernMessageReference,
    RequestBudget,
)
from librus_python_api.exceptions import ErrorKind, LibrusError
from librus_python_api.files import publish_attachment
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ResourceError
from mcp.types import ToolAnnotations
from pydantic import Field

from librus_mcp.message_schemas import MessageReferenceInput
from librus_mcp.message_tools import require_binding
from librus_mcp.read_schemas import AccountAliasInput, NumericID
from librus_mcp.resources import RESOURCE_TTL_SECONDS
from librus_mcp.runtime import Runtime
from librus_mcp.schemas import HexDigest, WireModel


class AttachmentInput(WireModel):
    message: MessageReferenceInput
    identifier: NumericID
    archived: Annotated[bool, Field(strict=True)] = False

    def native(self) -> MessageAttachmentReference | ModernMessageAttachmentReference:
        message = self.message.native()
        if isinstance(message, ModernMessageReference):
            return ModernMessageAttachmentReference(
                message=message, identifier=self.identifier, archived=self.archived
            )
        if not isinstance(message, MessageReference) or self.archived:
            raise LibrusError(ErrorKind.INVALID_INPUT)
        return MessageAttachmentReference(message=message, identifier=self.identifier)


class SavedAttachmentResult(WireModel):
    filename: str
    local_path: str
    size_bytes: int
    content_type: str | None
    sha256: HexDigest
    resource_uri: str | None
    resource_ttl_seconds: int | None


def register_attachment_tools(server: MCPServer[Runtime]) -> None:
    server.tool(annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True))(
        download_attachment
    )
    server.resource(
        "librus-attachment://files/{token}",
        mime_type="application/octet-stream",
        description="Inert runtime-only attachment snapshot; expires after 15 minutes and on restart.",
    )(read_attachment)


async def download_attachment(
    account_alias: AccountAliasInput,
    attachment_ref: AttachmentInput,
    filename: Annotated[str, Field(min_length=1, max_length=4096)],
    ctx: Context[Runtime, Any],
    max_bytes: Annotated[int, Field(strict=True, ge=1, le=50 * 1024 * 1024)] = 10 * 1024 * 1024,
) -> SavedAttachmentResult:
    """Save a selected attachment to the configured private native-v2 directory; never opens a body."""
    runtime = ctx.request_context.lifespan_context
    if not runtime.config.features.attachments:
        raise LibrusError(ErrorKind.UNSUPPORTED_CAPABILITY)
    message = attachment_ref.message
    require_binding(runtime, account_alias, message.account, message.context, message.backend.value)
    reference = attachment_ref.native()
    client = runtime.account(account_alias)
    budget = runtime.budget or RequestBudget(max_response_bytes=max_bytes + 4 * 1024 * 1024)
    stream = (
        client.stream_modern_attachment(reference, max_bytes=max_bytes, budget=budget)
        if isinstance(reference, ModernMessageAttachmentReference)
        else client.stream_attachment(reference, max_bytes=max_bytes, budget=budget)
    )
    saved = await publish_attachment(
        stream, runtime.attachment_resources.directory, filename=filename, max_bytes=max_bytes
    )
    # Publication is the native commit point. Optional resource hosting must
    # not turn an already committed download into an apparent failed transfer.
    # A rejected snapshot never creates a URI; the published digest remains the
    # caller's integrity check for subsequent local-file use.
    try:
        uri = runtime.attachment_resources.snapshot(saved)
    except LibrusError as error:
        if error.kind is not ErrorKind.STORAGE:
            raise
        uri = None
    return SavedAttachmentResult(
        filename=saved.path.name,
        local_path=str(saved.path),
        size_bytes=saved.size_bytes,
        content_type=saved.content_type,
        sha256=saved.sha256,
        resource_uri=uri,
        resource_ttl_seconds=RESOURCE_TTL_SECONDS if uri else None,
    )


# Resource templates use pydantic.validate_call, unlike tools. Specializing
# Context here revalidates the SDK's base instance and drops its private request
# state. Accept the SDK's exact public Context class at this injection boundary.
async def read_attachment(token: str, ctx: Context) -> bytes:
    try:
        runtime = cast(Runtime, ctx.request_context.lifespan_context)
        return runtime.attachment_resources.read(token)
    except LibrusError as error:
        raise ResourceError(error.kind.value.upper()) from None
