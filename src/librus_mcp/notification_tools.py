"""Explicit native at-least-once delivery, compact recovery status and acknowledgement."""

from typing import Annotated, Any, Literal

from librus_python_api import NotificationCategory
from librus_python_api.exceptions import ErrorKind, LibrusError
from librus_python_api.persistence import (
    NotificationBatch,
    NotificationRecoveryStatus,
    NotificationWorkflow,
)
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from librus_mcp.legacy_state import require_no_legacy_state
from librus_mcp.read_schemas import AccountAliasInput, HexDigest
from librus_mcp.runtime import Runtime
from librus_mcp.schemas import WireModel

Categories = Annotated[tuple[NotificationCategory, ...], Field(min_length=1, max_length=6)]


class NotificationsResult(WireModel):
    data: NotificationBatch
    delivery_semantics: Literal["at_least_once"] = "at_least_once"
    acknowledgement_required: Literal[True] = True


class NotificationStatusResult(WireModel):
    data: NotificationRecoveryStatus
    has_pending_work: bool


class NotificationAckResult(WireModel):
    context: HexDigest
    receipt: HexDigest
    acknowledged: Literal[True] = True


def register_notification_tools(server: MCPServer[Runtime]) -> None:
    server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, open_world_hint=True
        )
    )(get_new_notifications)
    server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))(
        get_notification_status
    )
    server.tool(annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False))(
        acknowledge_notifications
    )


async def get_new_notifications(
    account_alias: AccountAliasInput,
    categories: Categories,
    ctx: Context[Runtime, Any],
    allow_consume_events: Annotated[bool, Field(strict=True)] = False,
) -> NotificationsResult:
    """Stage/replay selected categories until ack. Fresh agenda consumes require explicit consent; never opens bodies."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    store = runtime.notifications()
    require_no_legacy_state(runtime.config.state_dir, account_alias)
    workflow = NotificationWorkflow(
        client, store, messages_backend=runtime.messaging_backend(account_alias)
    )
    batch = await workflow.poll(
        categories=categories, allow_consume_events=allow_consume_events, budget=runtime.budget
    )
    return NotificationsResult(data=batch)


async def get_notification_status(
    account_alias: AccountAliasInput, ctx: Context[Runtime, Any]
) -> NotificationStatusResult:
    """Inspect delivery/raw/uncertainty offline, without clearing, polling, acknowledging or registering a context."""
    runtime = ctx.request_context.lifespan_context
    status = await runtime.notifications().recovery_status(
        context=runtime.account(account_alias).context
    )
    return NotificationStatusResult(data=status, has_pending_work=status.has_pending_work)


async def acknowledge_notifications(
    account_alias: AccountAliasInput,
    receipt: HexDigest,
    context: HexDigest,
    ctx: Context[Runtime, Any],
) -> NotificationAckResult:
    """Commit a delivered batch's receipt. Call only after delivery; most recent ack is idempotent."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    if client.context.identifier != context:
        raise LibrusError(ErrorKind.INVALID_INPUT)
    await runtime.notifications().acknowledge(receipt, context=client.context)
    return NotificationAckResult(context=client.context.identifier, receipt=receipt)
