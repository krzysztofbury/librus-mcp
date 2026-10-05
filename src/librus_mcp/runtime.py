"""One shared native service per MCP lifespan, with no eager authentication."""

from contextlib import AsyncExitStack
from types import TracebackType
from typing import Self

from librus_python_api import (
    AccountClient,
    ConnectionSettings,
    LibrusService,
    MessagingBackend,
    RequestBudget,
)
from librus_python_api.exceptions import ErrorKind, LibrusError
from librus_python_api.files import prepare_attachment_directory
from librus_python_api.persistence import NotificationLimits, NotificationStore, PersistenceStore

from librus_mcp.config import AppConfig
from librus_mcp.resources import AttachmentResources


def notification_limits() -> NotificationLimits:
    """Consumer wire bounds apply before native staging, bootstrap and replay."""
    return NotificationLimits(
        batch_bytes=48 * 1024, replay_bytes=32 * 1024, batch_items=128, replay_events=128
    )


class Runtime:
    def __init__(
        self,
        config: AppConfig,
        *,
        connection: ConnectionSettings | None = None,
        budget: RequestBudget | None = None,
    ) -> None:
        self.config = config
        self._stack = AsyncExitStack()
        self._send_store: PersistenceStore | None = None
        self._notification_store: NotificationStore | None = None
        self.attachment_resources = AttachmentResources(config.download_dir / "native-v2")
        # Hosts can bound a whole short-lived workflow across multiple tool calls.
        # Normal serving passes None and uses the API's per-operation defaults.
        self.budget = budget
        self._backends = {account.alias: account.messaging_backend for account in config.accounts}
        self.service = LibrusService(
            {account.alias: account.credentials() for account in config.accounts},
            context_key=config.key_bytes(),
            connection=connection,
        )

    def account(self, alias: str) -> AccountClient:
        if alias not in {account.alias for account in self.config.accounts}:
            raise LibrusError(ErrorKind.INVALID_INPUT)
        return self.service.account(alias)

    def messaging_backend(self, alias: str) -> MessagingBackend:
        self.account(alias)
        return self._backends[alias]

    def sends(self) -> PersistenceStore:
        if self._send_store is None or not self.config.features.send_message:
            raise LibrusError(ErrorKind.UNSUPPORTED_CAPABILITY)
        return self._send_store

    def notifications(self) -> NotificationStore:
        if self._notification_store is None or not self.config.features.notifications:
            raise LibrusError(ErrorKind.UNSUPPORTED_CAPABILITY)
        return self._notification_store

    async def __aenter__(self) -> Self:
        try:
            await self._stack.enter_async_context(self.service)
            if self.config.features.send_message or self.config.features.notifications:
                await prepare_attachment_directory(self.config.state_dir)
            if self.config.features.send_message:
                self._send_store = await self._stack.enter_async_context(
                    PersistenceStore(self.config.state_dir / "native-v2")
                )
            if self.config.features.notifications:
                # A native batch is serialized into both structured and text MCP
                # content. Bound staging before side effects, leaving room for
                # escaping/SDK formatting under the complete 512 KiB wire cap.
                self._notification_store = await self._stack.enter_async_context(
                    NotificationStore(
                        self.config.state_dir / "native-v2",
                        limits=notification_limits(),
                    )
                )
            if self.config.features.attachments:
                await prepare_attachment_directory(self.config.download_dir)
                await prepare_attachment_directory(self.attachment_resources.directory)
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            await self._stack.__aexit__(exc_type, exc, traceback)
        finally:
            self.attachment_resources.close()
