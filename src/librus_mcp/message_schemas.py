"""Context/backend-bound MCP messaging inputs; native payloads remain typed."""

from typing import Annotated, Literal

from librus_python_api import (
    Identity,
    MessageContent,
    MessageFolder,
    MessageReference,
    MessagesCursor,
    MessageSummary,
    MessagingBackend,
    ModernMessageContent,
    ModernMessageReference,
    ModernMessagesCursor,
    ModernMessageSummary,
    ModernRecipient,
    ModernRecipientTypeReference,
    Observation,
    Recipient,
    RecipientGroupChoice,
    RecipientGroupReference,
)
from pydantic import Field

from librus_mcp.read_schemas import AccountAliasInput, NumericID
from librus_mcp.schemas import HexDigest, Pagination, WireModel

SeenIDs = Annotated[tuple[NumericID, ...], Field(max_length=2000)]


class MessageReferenceInput(WireModel):
    context: HexDigest
    backend: MessagingBackend
    folder: MessageFolder
    identifier: NumericID
    account: AccountAliasInput

    def native(self) -> MessageReference | ModernMessageReference:
        if self.backend is MessagingBackend.MODERN:
            return ModernMessageReference(
                folder=self.folder, identifier=self.identifier, account=self.account
            )
        return MessageReference(
            folder=self.folder, identifier=self.identifier, account=self.account
        )


class LegacyCursor(WireModel):
    backend: Literal["legacy"] = "legacy"
    context: HexDigest
    account: AccountAliasInput
    folder: MessageFolder
    page: Annotated[int, Field(strict=True, ge=0, le=999)]
    offset: Annotated[int, Field(strict=True, ge=0, le=50)]
    page_count: Annotated[int, Field(strict=True, ge=0, le=1000)]
    fingerprint: HexDigest
    seen_ids: SeenIDs

    def native(self) -> MessagesCursor:
        return MessagesCursor(
            account=self.account,
            folder=self.folder,
            page=self.page,
            offset=self.offset,
            page_count=self.page_count,
            fingerprint=self.fingerprint,
            seen_ids=self.seen_ids,
        )


class ModernCursor(WireModel):
    backend: Literal["modern"] = "modern"
    context: HexDigest
    account: AccountAliasInput
    folder: MessageFolder
    page: Annotated[int, Field(strict=True, ge=1, le=1000)]
    offset: Annotated[int, Field(strict=True, ge=0, le=50)]
    page_size: Annotated[int, Field(strict=True, ge=1, le=50)]
    total_count: Annotated[int, Field(strict=True, ge=0, le=50000)]
    fingerprint: HexDigest
    seen_ids: SeenIDs

    def native(self) -> ModernMessagesCursor:
        return ModernMessagesCursor(
            account=self.account,
            folder=self.folder,
            page=self.page,
            offset=self.offset,
            page_size=self.page_size,
            total_count=self.total_count,
            fingerprint=self.fingerprint,
            seen_ids=self.seen_ids,
        )


MessageCursorInput = Annotated[LegacyCursor | ModernCursor, Field(discriminator="backend")]


class MessagePagination(WireModel):
    next_cursor: MessageCursorInput | None
    truncated: bool
    reason: Literal["item_limit", "page_limit"] | None
    pages_fetched: int
    duplicates_skipped: int
    consistency: Literal["best_effort"] = "best_effort"


class MessageItemOutput(WireModel):
    reference: MessageReferenceInput
    summary: MessageSummary | ModernMessageSummary


class MessagesResult(WireModel):
    items: tuple[MessageItemOutput, ...]
    backend: MessagingBackend
    folder: MessageFolder
    identity: Identity
    observation: Observation
    pagination: MessagePagination


class MessageContentResult(WireModel):
    context: HexDigest
    backend: MessagingBackend
    data: MessageContent | ModernMessageContent


class RecipientTypeInput(WireModel):
    context: HexDigest
    backend: MessagingBackend
    account: AccountAliasInput
    identifier: Annotated[str, Field(min_length=1, max_length=80)]
    selection_id: NumericID = "0"
    include_virtual: Annotated[bool, Field(strict=True)] = False

    def legacy(self) -> RecipientGroupReference:
        return RecipientGroupReference(
            identifier=self.identifier, account=self.account, selection_id=self.selection_id
        )

    def modern(self) -> ModernRecipientTypeReference:
        return ModernRecipientTypeReference(
            identifier=self.identifier, account=self.account, include_virtual=self.include_virtual
        )


class RecipientTypeOutput(WireModel):
    reference: RecipientTypeInput
    label: str
    lookup_supported: bool
    available: bool | None


class RecipientTypesResult(WireModel):
    items: tuple[RecipientTypeOutput, ...]
    backend: MessagingBackend
    identity: Identity
    observation: Observation
    pagination: Pagination = Field(default_factory=Pagination)


class RecipientChoicesResult(WireModel):
    # Choices are accompanied by the same context/backend needed for next selection.
    context: HexDigest
    backend: Literal["legacy"] = "legacy"
    items: tuple[RecipientGroupChoice, ...]
    identity: Identity
    observation: Observation
    pagination: Pagination = Field(default_factory=Pagination)


class RecipientsResult(WireModel):
    context: HexDigest
    backend: MessagingBackend
    items: tuple[Recipient | ModernRecipient, ...]
    identity: Identity
    observation: Observation
    pagination: Pagination = Field(default_factory=Pagination)
