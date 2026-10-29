"""Native message/directory reads with explicit source selection, never fallback."""

from typing import Annotated, Any

from librus_python_api import (
    MessageFolder,
    Messages,
    MessagesCursor,
    MessagingBackend,
    ModernMessageReference,
    ModernMessages,
    ModernMessagesCursor,
    ModernTeacherSubject,
)
from librus_python_api.exceptions import ErrorKind, LibrusError
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from librus_mcp.message_schemas import (
    CorrespondentItem,
    CorrespondentReferenceInput,
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
    UnreadCountsResult,
)
from librus_mcp.presentation import validate_window_cursor, window_page
from librus_mcp.read_schemas import AccountAliasInput, Cursor, FetchPages, PagedResult, PageLimit
from librus_mcp.runtime import Runtime
from librus_mcp.schemas import PresentationCursor


def register_message_tools(server: MCPServer[Runtime]) -> None:
    # Changes Librus's remembered view, never school data.
    selection = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
    ordinary = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    server.tool(title="Messages", annotations=selection)(get_messages)
    server.tool(
        title="Read message",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, open_world_hint=True
        ),
    )(get_message_content)
    server.tool(title="Recipient types", annotations=ordinary)(get_recipient_types)
    server.tool(title="Recipient choices", annotations=ordinary)(get_recipient_choices)
    server.tool(title="Recipients", annotations=selection)(get_recipients)
    server.tool(title="Message correspondents", annotations=ordinary)(get_message_correspondents)
    server.tool(title="Teacher subjects", annotations=ordinary)(get_teacher_subjects)
    server.tool(title="Unread message counts", annotations=ordinary)(get_message_unread_counts)


def require_binding(runtime: Runtime, alias: str, account: str, context: str, backend: str) -> None:
    if account != alias or context != runtime.account(alias).context.identifier:
        raise LibrusError(ErrorKind.INVALID_INPUT)
    if backend != runtime.messaging_backend(alias).value:
        raise LibrusError(ErrorKind.INVALID_INPUT)


async def get_messages(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
    folder: Annotated[
        MessageFolder, Field(description="received or sent mail.")
    ] = MessageFolder.RECEIVED,
    cursor: Cursor[MessageCursorInput] = None,
    limit: PageLimit = 100,
    max_pages: FetchPages = 2,
    page_size: Annotated[
        int,
        Field(
            strict=True,
            ge=1,
            le=50,
            description="Messages per Librus page; legacy accepts only 50.",
        ),
    ] = 50,
    archived: Annotated[
        bool, Field(strict=True, description="Modern only: list earlier years' archive.")
    ] = False,
    correspondent: Annotated[
        CorrespondentReferenceInput | None,
        Field(description="Modern only: a reference from get_message_correspondents."),
    ] = None,
    unread_only: Annotated[
        bool, Field(strict=True, description="Modern only: unread received mail only.")
    ] = False,
) -> MessagesResult:
    """List message summaries (correspondent, subject, date, read state) without opening them; use get_message_content for the text. On legacy accounts the folder choice changes the view Librus remembers. Modern accounts can list the archive or filter current mail by correspondent or unread_only; archives cannot be filtered. Repeat the same filters with cursor."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    backend = runtime.messaging_backend(account_alias)
    if correspondent is not None:
        require_binding(
            runtime,
            account_alias,
            correspondent.account,
            correspondent.context,
            correspondent.backend,
        )
        if correspondent.folder != folder:
            raise LibrusError(ErrorKind.INVALID_INPUT)
    if cursor is not None:
        require_binding(runtime, account_alias, cursor.account, cursor.context, cursor.backend)
        if cursor.folder != folder:
            raise LibrusError(ErrorKind.INVALID_INPUT)
    if backend is MessagingBackend.MODERN:
        if cursor is not None and not isinstance(cursor, ModernCursor):
            raise LibrusError(ErrorKind.INVALID_INPUT)
        if cursor is not None and (
            cursor.archived != archived
            or cursor.correspondent != (correspondent.identifier if correspondent else None)
            or cursor.unread_only != unread_only
        ):
            raise LibrusError(ErrorKind.INVALID_INPUT)
        modern = await client.modern_messages(
            folder=folder,
            cursor=None if cursor is None else cursor.native(),
            limit=limit,
            max_pages=max_pages,
            page_size=page_size,
            archived=archived,
            correspondent=correspondent.native() if correspondent else None,
            unread_only=unread_only,
            budget=runtime.budget,
        )
        return message_result(modern, client.context.identifier, backend)
    else:
        if archived or correspondent is not None or unread_only:
            raise LibrusError(ErrorKind.UNSUPPORTED_CAPABILITY)
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
            archived=value.archived,
            correspondent=value.correspondent,
            unread_only=value.unread_only,
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
                    archived=item.reference.archived
                    if isinstance(item.reference, ModernMessageReference)
                    else False,
                ),
                summary=item,
            )
            for item in result.items
        ),
        backend=backend,
        folder=result.folder,
        identity=result.identity,
        observation=result.observation,
        archived=result.archived if isinstance(result, ModernMessages) else False,
        correspondent=(
            CorrespondentReferenceInput(
                context=context,
                folder=result.correspondent.folder,
                identifier=result.correspondent.identifier,
                account=result.correspondent.account,
            )
            if isinstance(result, ModernMessages) and result.correspondent
            else None
        ),
        unread_only=result.unread_only if isinstance(result, ModernMessages) else False,
        archiving_in_progress=result.archiving_in_progress
        if isinstance(result, ModernMessages)
        else None,
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
    message_ref: Annotated[
        MessageReferenceInput, Field(description="A message's reference from get_messages.")
    ],
    ctx: Context[Runtime, Any],
    allow_mark_read: Annotated[
        bool | None,
        Field(strict=True, description="false leaves a received message unread and unopened."),
    ] = None,
) -> MessageContentResult:
    """Get a message's full text and attachments. Opening a received message marks it read in Librus, as the app does. A server can require consent for that: on CONSENT_REQUIRED, ask the user, then call again with allow_mark_read=true. Archived messages cannot be opened."""
    runtime = ctx.request_context.lifespan_context
    require_binding(
        runtime, account_alias, message_ref.account, message_ref.context, message_ref.backend.value
    )
    if message_ref.archived:
        raise LibrusError(ErrorKind.UNSUPPORTED_CAPABILITY)
    mark_read = allow_mark_read is True
    if message_ref.folder is MessageFolder.RECEIVED:
        if allow_mark_read is None:
            mark_read = not runtime.config.features.mark_read_consent
        if not mark_read:
            raise LibrusError(ErrorKind.CONSENT_REQUIRED)
    reference = message_ref.native()
    client = runtime.account(account_alias)
    if isinstance(reference, ModernMessageReference):
        content = await client.modern_message_content(
            reference, allow_mark_read=mark_read, budget=runtime.budget
        )
        return MessageContentResult(
            context=client.context.identifier, backend=message_ref.backend, data=content
        )
    content_legacy = await client.message_content(
        reference, allow_mark_read=mark_read, budget=runtime.budget
    )
    return MessageContentResult(
        context=client.context.identifier, backend=message_ref.backend, data=content_legacy
    )


async def get_message_correspondents(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
    folder: Annotated[
        MessageFolder, Field(description="received or sent mail.")
    ] = MessageFolder.RECEIVED,
    cursor: Cursor[PresentationCursor] = None,
    limit: PageLimit = 100,
) -> PagedResult[CorrespondentItem]:
    """Modern accounts: list the people in a mailbox folder, to filter get_messages by correspondent. These references cannot address a new message; use get_recipients for that."""
    runtime = ctx.request_context.lifespan_context
    if runtime.messaging_backend(account_alias) is not MessagingBackend.MODERN:
        raise LibrusError(ErrorKind.UNSUPPORTED_CAPABILITY)
    client = runtime.account(account_alias)
    query = ("message-correspondents", "modern", folder.value)
    validate_window_cursor(cursor, client.context.identifier, query)
    result = await client.modern_correspondents(folder=folder, budget=runtime.budget)
    items = tuple(
        CorrespondentItem(
            reference=CorrespondentReferenceInput(
                context=client.context.identifier,
                folder=item.reference.folder,
                identifier=item.reference.identifier,
                account=item.reference.account,
            ),
            first_name=item.first_name,
            last_name=item.last_name,
        )
        for item in result.items
    )
    selected, pagination = window_page(
        items, context=client.context.identifier, query=query, cursor=cursor, limit=limit
    )
    return PagedResult[CorrespondentItem](
        items=selected,
        identity=result.identity,
        observation=result.observation,
        pagination=pagination,
    )


async def get_teacher_subjects(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
    cursor: Cursor[PresentationCursor] = None,
    limit: PageLimit = 100,
) -> PagedResult[ModernTeacherSubject]:
    """Modern accounts: list teachers with the subjects they teach. The IDs are informational and cannot address a message; use get_recipients for that."""
    runtime = ctx.request_context.lifespan_context
    if runtime.messaging_backend(account_alias) is not MessagingBackend.MODERN:
        raise LibrusError(ErrorKind.UNSUPPORTED_CAPABILITY)
    client = runtime.account(account_alias)
    query = ("teacher-subjects", "modern")
    validate_window_cursor(cursor, client.context.identifier, query)
    result = await client.modern_teacher_subjects(budget=runtime.budget)
    selected, pagination = window_page(
        result.items, context=client.context.identifier, query=query, cursor=cursor, limit=limit
    )
    return PagedResult[ModernTeacherSubject](
        items=selected,
        identity=result.identity,
        observation=result.observation,
        pagination=pagination,
    )


async def get_message_unread_counts(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
) -> UnreadCountsResult:
    """Modern accounts: get unread message counts for the current and archive folders without opening messages. Independent of get_new_notifications."""
    runtime = ctx.request_context.lifespan_context
    if runtime.messaging_backend(account_alias) is not MessagingBackend.MODERN:
        raise LibrusError(ErrorKind.UNSUPPORTED_CAPABILITY)
    return UnreadCountsResult(
        data=await runtime.account(account_alias).modern_unread_counts(budget=runtime.budget)
    )


async def get_recipient_types(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
) -> RecipientTypesResult:
    """List the recipient groups this login can message and whether each can be looked up. Pass a group's reference to get_recipients, or on legacy accounts to get_recipient_choices. Sends nothing."""
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
    recipient_type: Annotated[
        RecipientTypeInput, Field(description="A group's reference from get_recipient_types.")
    ],
    ctx: Context[Runtime, Any],
) -> RecipientChoicesResult:
    """Legacy accounts only: list the sub-choices of a hierarchical recipient group, such as classes. Put the chosen item's reference.selection_id into recipient_type for get_recipients. Modern accounts return UNSUPPORTED_CAPABILITY."""
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
    recipient_type: Annotated[
        RecipientTypeInput, Field(description="A group's reference from get_recipient_types.")
    ],
    ctx: Context[Runtime, Any],
) -> RecipientsResult:
    """List the people in one recipient group, to address a message. Modern students and parents groups include virtual accounts only with include_virtual=true in recipient_type. On legacy accounts the lookup changes this login's Librus form state. Nothing is sent."""
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
