"""Opt-in native durable sending; no consumer hashing, retries or token dictionary."""

from typing import Annotated, Any

from librus_python_api import MessagingBackend, SendAttempt
from librus_python_api.exceptions import ErrorKind, LibrusError
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from librus_mcp.message_tools import require_binding
from librus_mcp.read_schemas import AccountAliasInput
from librus_mcp.runtime import Runtime
from librus_mcp.send_schemas import (
    ConfirmationToken,
    LegacyRecipientInput,
    MessagePreviewResult,
    MessageSendResult,
    MessageSubmissionInput,
    ModernRecipientInput,
    SendHistoryResult,
    SendOutcomeResult,
)


def register_send_tools(server: MCPServer[Runtime]) -> None:
    local_write = ToolAnnotations(read_only_hint=False, open_world_hint=False)
    local_read = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    server.tool(annotations=local_write)(preview_message)
    server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, open_world_hint=True
        )
    )(send_message)
    server.tool(annotations=local_read)(get_send_outcome)
    server.tool(annotations=local_read)(get_send_history)


def prepare(runtime: Runtime, alias: str, message: MessageSubmissionInput) -> SendAttempt:
    runtime.sends()
    backend = runtime.messaging_backend(alias)
    for reference in message.recipients:
        require_binding(runtime, alias, reference.account, reference.context, reference.backend)
    client = runtime.account(alias)
    if backend is MessagingBackend.MODERN:
        modern = tuple(
            reference.native()
            for reference in message.recipients
            if isinstance(reference, ModernRecipientInput)
        )
        if len(modern) != len(message.recipients):
            raise LibrusError(ErrorKind.INVALID_INPUT)
        return client.prepare_modern_send(
            recipients=modern, subject=message.subject, body=message.body
        )
    legacy = tuple(
        reference.native()
        for reference in message.recipients
        if isinstance(reference, LegacyRecipientInput)
    )
    if len(legacy) != len(message.recipients):
        raise LibrusError(ErrorKind.INVALID_INPUT)
    return client.prepare_send(recipients=legacy, subject=message.subject, body=message.body)


async def preview_message(
    account_alias: AccountAliasInput,
    message: MessageSubmissionInput,
    ctx: Context[Runtime, Any],
) -> MessagePreviewResult:
    """Persist a five-minute exact-input preview without HTTP. Obtain human approval before sending."""
    runtime = ctx.request_context.lifespan_context
    attempt = prepare(runtime, account_alias, message)
    confirmation = await runtime.sends().preview_send(attempt)
    backend = runtime.messaging_backend(account_alias)
    return MessagePreviewResult(
        account_alias=account_alias,
        backend=backend,
        message=message,
        confirmation_token=confirmation.token,
        expires_at=confirmation.expires_at,
    )


async def send_message(
    account_alias: AccountAliasInput,
    message: MessageSubmissionInput,
    confirmation_token: ConfirmationToken,
    ctx: Context[Runtime, Any],
    confirm: Annotated[bool, Field(strict=True)] = False,
) -> MessageSendResult:
    """Redeem a preview once after explicit approval. UNKNOWN/CLAIMED require reconciliation, never retry."""
    if not confirm:
        raise LibrusError(ErrorKind.INVALID_INPUT)
    runtime = ctx.request_context.lifespan_context
    attempt = prepare(runtime, account_alias, message)
    result = await runtime.sends().execute_send(confirmation_token, attempt, budget=runtime.budget)
    durable = await runtime.sends().send_outcome(
        confirmation_token, context=runtime.account(account_alias).context
    )
    return MessageSendResult(data=result, durable=durable)


async def get_send_outcome(
    account_alias: AccountAliasInput,
    confirmation_token: ConfirmationToken,
    ctx: Context[Runtime, Any],
) -> SendOutcomeResult:
    """Inspect durable preview/send outcome offline; this never authorizes resubmission."""
    runtime = ctx.request_context.lifespan_context
    result = await runtime.sends().send_outcome(
        confirmation_token, context=runtime.account(account_alias).context
    )
    return SendOutcomeResult(data=result)


async def get_send_history(
    account_alias: AccountAliasInput, ctx: Context[Runtime, Any]
) -> SendHistoryResult:
    """Inspect bounded durable history offline, including uncertainty after lost tokens/responses."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    return SendHistoryResult(
        items=await runtime.sends().send_history(context=client.context),
        context=client.context.identifier,
    )
