"""Native message/directory reads with explicit source selection, never fallback."""

from typing import Annotated, Any

from librus_python_api import (
    MessageFolder,
    MessageReference,
    Messages,
    MessagesCursor,
    MessagingBackend,
    ModernMessageReference,
    ModernMessages,
    ModernMessagesCursor,
)
from librus_python_api.exceptions import ErrorKind, LibrusError
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from librus_mcp.message_schemas import (
    LegacyCursor,
    MessageContentResult,
    MessageCursorInput,
    MessageItemOutput,
    MessagePagination,
    MessageReferenceInput,
    MessagesResult,
    ModernCursor,
    RecipientChoicesResult,
    RecipientsResult,
    RecipientTypeInput,
    RecipientTypeOutput,
    RecipientTypesResult,
)
from librus_mcp.read_schemas import AccountAliasInput, Limit, MaxPages
from librus_mcp.runtime import Runtime


def register_message_tools(server: MCPServer[Runtime]) -> None:
    selection = ToolAnnotations(read_only_hint=False, open_world_hint=True)
    ordinary = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    server.tool(annotations=selection)(get_messages)
    server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, open_world_hint=True
        )
    )(get_message_content)
    server.tool(annotations=ordinary)(get_recipient_types)
    server.tool(annotations=ordinary)(get_recipient_choices)
    server.tool(annotations=selection)(get_recipients)


def require_binding(runtime: Runtime, alias: str, account: str, context: str, backend: str) -> None:
    if account != alias or context != runtime.account(alias).context.identifier:
        raise LibrusError(ErrorKind.INVALID_INPUT)
    if backend != runtime.messaging_backend(alias).value:
        raise LibrusError(ErrorKind.INVALID_INPUT)


async def get_messages(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
    folder: MessageFolder = MessageFolder.RECEIVED,
    cursor: MessageCursorInput | None = None,
    limit: Limit = 100,
    max_pages: MaxPages = 2,
    page_size: Annotated[int, Field(strict=True, ge=1, le=50)] = 50,
) -> MessagesResult:
    """Read bounded message summaries from the configured backend; never opens bodies or falls back."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    backend = runtime.messaging_backend(account_alias)
    if cursor is not None:
        require_binding(runtime, account_alias, cursor.account, cursor.context, cursor.backend)
        if cursor.folder != folder:
            raise LibrusError(ErrorKind.INVALID_INPUT)
    if backend is MessagingBackend.MODERN:
        if cursor is not None and not isinstance(cursor, ModernCursor):
            raise LibrusError(ErrorKind.INVALID_INPUT)
        modern = await client.modern_messages(
            folder=folder,
            cursor=None if cursor is None else cursor.native(),
            limit=limit,
            max_pages=max_pages,
            page_size=page_size,
            budget=runtime.budget,
        )
        return message_result(modern, client.context.identifier, backend)
    else:
        if cursor is not None and not isinstance(cursor, LegacyCursor):
            raise LibrusError(ErrorKind.INVALID_INPUT)
        if page_size != 50:
            raise LibrusError(ErrorKind.INVALID_INPUT)
        legacy = await client.messages(
            folder=folder,
            cursor=None if cursor is None else cursor.native(),
            limit=limit,
            max_pages=max_pages,
            budget=runtime.budget,
        )
        return message_result(legacy, client.context.identifier, backend)


def message_result(
    result: Messages | ModernMessages, context: str, backend: MessagingBackend
) -> MessagesResult:
    next_cursor: MessageCursorInput | None = None
    if isinstance(result.next_cursor, ModernMessagesCursor):
        value = result.next_cursor
        next_cursor = ModernCursor(
            context=context,
            account=value.account,
            folder=value.folder,
            page=value.page,
            offset=value.offset,
            page_size=value.page_size,
            total_count=value.total_count,
            fingerprint=value.fingerprint,
            seen_ids=value.seen_ids,
        )
    elif isinstance(result.next_cursor, MessagesCursor):
        value_legacy = result.next_cursor
        next_cursor = LegacyCursor(
            context=context,
            account=value_legacy.account,
            folder=value_legacy.folder,
            page=value_legacy.page,
            offset=value_legacy.offset,
            page_count=value_legacy.page_count,
            fingerprint=value_legacy.fingerprint,
            seen_ids=value_legacy.seen_ids,
        )
    return MessagesResult(
        items=tuple(
            MessageItemOutput(
                reference=MessageReferenceInput(
                    context=context,
                    backend=backend,
                    folder=item.reference.folder,
                    identifier=item.reference.identifier,
                    account=item.reference.account,
                ),
                summary=item,
            )
            for item in result.items
        ),
        backend=backend,
        folder=result.folder,
        identity=result.identity,
        observation=result.observation,
        pagination=MessagePagination(
            next_cursor=next_cursor,
            truncated=next_cursor is not None,
            reason=result.truncation_reason,
            pages_fetched=result.pages_fetched,
            duplicates_skipped=result.duplicates_skipped,
        ),
    )


async def get_message_content(
    account_alias: AccountAliasInput,
    message_ref: MessageReferenceInput,
    ctx: Context[Runtime, Any],
    allow_mark_read: Annotated[bool, Field(strict=True)] = False,
) -> MessageContentResult:
    """Read inert message content; received opens require explicit allow_mark_read=true consent."""
    runtime = ctx.request_context.lifespan_context
    require_binding(
        runtime, account_alias, message_ref.account, message_ref.context, message_ref.backend.value
    )
    if message_ref.folder is MessageFolder.RECEIVED and not allow_mark_read:
        raise LibrusError(ErrorKind.INVALID_INPUT)
    reference = message_ref.native()
    client = runtime.account(account_alias)
    if isinstance(reference, ModernMessageReference):
        content = await client.modern_message_content(
            reference, allow_mark_read=allow_mark_read, budget=runtime.budget
        )
        return MessageContentResult(
            context=client.context.identifier, backend=message_ref.backend, data=content
        )
    if not isinstance(reference, MessageReference):
        raise LibrusError(ErrorKind.INVALID_INPUT)
    content_legacy = await client.message_content(
        reference, allow_mark_read=allow_mark_read, budget=runtime.budget
    )
    return MessageContentResult(
        context=client.context.identifier, backend=message_ref.backend, data=content_legacy
    )


async def get_recipient_types(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
) -> RecipientTypesResult:
    """Read backend-specific recipient branches and lookup capabilities without sending."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    backend = runtime.messaging_backend(account_alias)
    if backend is MessagingBackend.MODERN:
        modern = await client.modern_recipient_types(budget=runtime.budget)
        items = tuple(
            RecipientTypeOutput(
                reference=RecipientTypeInput(
                    context=client.context.identifier,
                    backend=backend,
                    account=item.reference.account,
                    identifier=item.reference.identifier,
                    include_virtual=item.reference.include_virtual,
                ),
                label=item.label,
                lookup_supported=item.lookup_supported,
                available=None,
            )
            for item in modern.items
        )
        return RecipientTypesResult(
            items=items, backend=backend, identity=modern.identity, observation=modern.observation
        )
    legacy = await client.recipient_groups(budget=runtime.budget)
    items = tuple(
        RecipientTypeOutput(
            reference=RecipientTypeInput(
                context=client.context.identifier,
                backend=backend,
                account=item.reference.account,
                identifier=item.reference.identifier,
                selection_id=item.reference.selection_id,
            ),
            label=item.label,
            lookup_supported=item.lookup_supported,
            available=item.available,
        )
        for item in legacy.groups
    )
    return RecipientTypesResult(
        items=items, backend=backend, identity=legacy.identity, observation=legacy.observation
    )


async def get_recipient_choices(
    account_alias: AccountAliasInput,
    recipient_type: RecipientTypeInput,
    ctx: Context[Runtime, Any],
) -> RecipientChoicesResult:
    """Read legacy hierarchical group choices; unsupported on a modern-configured account."""
    runtime = ctx.request_context.lifespan_context
    require_binding(
        runtime,
        account_alias,
        recipient_type.account,
        recipient_type.context,
        recipient_type.backend.value,
    )
    if recipient_type.backend is not MessagingBackend.LEGACY:
        raise LibrusError(ErrorKind.UNSUPPORTED_CAPABILITY)
    if recipient_type.include_virtual:
        raise LibrusError(ErrorKind.INVALID_INPUT)
    client = runtime.account(account_alias)
    result = await client.recipient_group_choices(recipient_type.legacy(), budget=runtime.budget)
    return RecipientChoicesResult(
        context=client.context.identifier,
        items=result.items,
        identity=result.identity,
        observation=result.observation,
    )


async def get_recipients(
    account_alias: AccountAliasInput,
    recipient_type: RecipientTypeInput,
    ctx: Context[Runtime, Any],
) -> RecipientsResult:
    """Read recipients from a bound type; no fallback, automatic virtual expansion or send."""
    runtime = ctx.request_context.lifespan_context
    require_binding(
        runtime,
        account_alias,
        recipient_type.account,
        recipient_type.context,
        recipient_type.backend.value,
    )
    client = runtime.account(account_alias)
    if recipient_type.backend is MessagingBackend.MODERN:
        if recipient_type.selection_id != "0":
            raise LibrusError(ErrorKind.INVALID_INPUT)
        modern = await client.modern_recipients(recipient_type.modern(), budget=runtime.budget)
        return RecipientsResult(
            context=client.context.identifier,
            backend=recipient_type.backend,
            items=modern.items,
            identity=modern.identity,
            observation=modern.observation,
        )
    if recipient_type.include_virtual:
        raise LibrusError(ErrorKind.INVALID_INPUT)
    legacy = await client.recipients(recipient_type.legacy(), budget=runtime.budget)
    return RecipientsResult(
        context=client.context.identifier,
        backend=recipient_type.backend,
        items=legacy.items,
        identity=legacy.identity,
        observation=legacy.observation,
    )
