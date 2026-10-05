"""Exact payloads for native durable preview/claim/outcome, not MCP token state."""

from datetime import datetime
from typing import Annotated, Literal

from librus_python_api import (
    MessagingBackend,
    ModernRecipientReference,
    RecipientReference,
    SendResult,
)
from librus_python_api.persistence import DurableSendOutcome, DurableSendRecord
from pydantic import Field

from librus_mcp.read_schemas import AccountAliasInput, HexDigest, NumericID
from librus_mcp.schemas import WireModel

ConfirmationToken = Annotated[
    str, Field(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]


class LegacyRecipientInput(WireModel):
    backend: Literal["legacy"] = "legacy"
    context: HexDigest
    account: AccountAliasInput
    identifier: NumericID
    group_type: Annotated[str, Field(min_length=1, max_length=80)]
    selection_id: NumericID

    def native(self) -> RecipientReference:
        return RecipientReference(
            identifier=self.identifier,
            account=self.account,
            group_type=self.group_type,
            selection_id=self.selection_id,
        )


class ModernRecipientInput(WireModel):
    backend: Literal["modern"] = "modern"
    context: HexDigest
    account: AccountAliasInput
    account_id: NumericID
    user_id: NumericID
    recipient_type: Annotated[str, Field(min_length=1, max_length=80)]
    class_label: Annotated[str, Field(max_length=1024)]
    include_virtual: Annotated[bool, Field(strict=True)] = False

    def native(self) -> ModernRecipientReference:
        return ModernRecipientReference(
            account_id=self.account_id,
            user_id=self.user_id,
            account=self.account,
            recipient_type=self.recipient_type,
            class_label=self.class_label,
            include_virtual=self.include_virtual,
        )


RecipientInput = Annotated[
    LegacyRecipientInput | ModernRecipientInput, Field(discriminator="backend")
]


class MessageSubmissionInput(WireModel):
    recipients: Annotated[tuple[RecipientInput, ...], Field(min_length=1, max_length=50)]
    subject: Annotated[str, Field(min_length=1, max_length=200, repr=False)]
    body: Annotated[str, Field(min_length=1, max_length=15000, repr=False)]


class MessagePreviewResult(WireModel):
    account_alias: str
    backend: MessagingBackend
    message: MessageSubmissionInput
    confirmation_token: str = Field(repr=False)
    expires_at: datetime
    human_approval_required: Literal[True] = True


class MessageSendResult(WireModel):
    data: SendResult
    durable: DurableSendOutcome


class SendOutcomeResult(WireModel):
    data: DurableSendOutcome


class SendHistoryResult(WireModel):
    items: tuple[DurableSendRecord, ...]
    context: HexDigest
