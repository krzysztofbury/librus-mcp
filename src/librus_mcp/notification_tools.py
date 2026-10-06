"""Explicit native at-least-once delivery, compact recovery status and acknowledgement."""

import asyncio
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from librus_python_api import NotificationCategory, RecentScheduleEvent
from librus_python_api.exceptions import ErrorKind, LibrusError
from librus_python_api.persistence import (
    NotificationBatch,
    NotificationBootstrap,
    NotificationRecoveryStatus,
    NotificationWorkflow,
)
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from librus_mcp.config import ConfigError, notice
from librus_mcp.legacy_state import (
    inventory_legacy,
    legacy_files,
    legacy_stems,
    restrict_own_files,
)
from librus_mcp.read_schemas import AccountAliasInput
from librus_mcp.runtime import Runtime
from librus_mcp.schemas import HexDigest, WireModel

Categories = Annotated[tuple[NotificationCategory, ...], Field(min_length=1, max_length=6)]


class NotificationsResult(WireModel):
    data: NotificationBatch
    delivery_semantics: Literal["at_least_once"] = "at_least_once"
    acknowledgement_required: Literal[True] = True


class NotificationStatusResult(WireModel):
    data: NotificationRecoveryStatus
    has_pending_work: bool


class BatchContextInput(WireModel):
    """The batch's `context` object, accepted verbatim as returned by a poll."""

    alias: AccountAliasInput
    identifier: HexDigest


class NotificationAckResult(WireModel):
    context: HexDigest
    receipt: HexDigest
    acknowledged: Literal[True] = True


LEGACY_ARCHIVE = "legacy-1x"


def _archive(directory: Path, paths: tuple[Path, ...]) -> None:
    # Preserve originals for manual recovery; only move them out of the scan.
    archive = directory / LEGACY_ARCHIVE
    archive.mkdir(mode=0o700, exist_ok=True)
    for path in paths:
        target = archive / path.name
        for index in range(1, 1000):
            if not os.path.lexists(target):
                break
            target = archive / f"{path.name}.{index}"
        try:
            path.rename(target)
        except FileNotFoundError:
            continue  # Another process adopted the same file first.


async def adopt_legacy_state(runtime: Runtime, alias: str) -> None:
    """Adopt 1.x notification files for one account, once, without operator steps.

    Pending agenda events were already consumed upstream, so they are imported
    and delivered. 1.x seen-IDs cannot be translated to native identifiers; the
    native baseline starts from Librus' own "new" views instead, which can repeat
    a few already reported items once but never hides new ones. Originals move to
    state_dir/legacy-1x. A store that is already native only archives the files.
    """
    directory = runtime.config.state_dir
    if not await asyncio.to_thread(legacy_files, directory, alias):
        return
    async with runtime.legacy_lock:
        paths = await asyncio.to_thread(legacy_files, directory, alias)
        if not paths:
            return
        stems = set(legacy_stems(alias))
        if any(
            stems.intersection(legacy_stems(account.alias))
            for account in runtime.config.accounts
            if account.alias != alias
        ):
            raise LibrusError(ErrorKind.STORAGE)
        client = runtime.account(alias)
        store = runtime.notifications()
        status = await store.recovery_status(context=client.context)
        imported = 0
        if not status.initialized and not status.has_pending_work:
            events: tuple[RecentScheduleEvent, ...] = ()
            if os.name == "posix":
                # Windows 1.x files have no qualified private read boundary.
                try:
                    await asyncio.to_thread(restrict_own_files, paths)
                    inventory = await asyncio.to_thread(inventory_legacy, directory, alias)
                except ConfigError:
                    raise LibrusError(ErrorKind.STORAGE) from None
                events = inventory.pending_events
            result = await store.bootstrap(
                NotificationBootstrap(context=client.context, mappings=(), pending_events=events),
                context=client.context,
            )
            if not result.imported:
                raise LibrusError(ErrorKind.STORAGE)
            imported = len(events)
        try:
            await asyncio.to_thread(_archive, directory, paths)
        except OSError:
            raise LibrusError(ErrorKind.STORAGE) from None
        notice(
            f"adopted 1.x notification state for one account ({imported} pending "
            f"events imported); originals kept in {directory / LEGACY_ARCHIVE}"
        )


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
    await adopt_legacy_state(runtime, account_alias)
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
    context: HexDigest | BatchContextInput,
    ctx: Context[Runtime, Any],
) -> NotificationAckResult:
    """Commit a delivered batch's receipt and context (object or identifier). Call only after delivery."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    identifier = context if isinstance(context, str) else context.identifier
    if isinstance(context, BatchContextInput) and context.alias != account_alias:
        raise LibrusError(ErrorKind.INVALID_INPUT)
    if client.context.identifier != identifier:
        raise LibrusError(ErrorKind.INVALID_INPUT)
    await runtime.notifications().acknowledge(receipt, context=client.context)
    return NotificationAckResult(context=client.context.identifier, receipt=receipt)
