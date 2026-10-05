"""Offline application diagnostics using disposable public native storage only."""

import tempfile
from pathlib import Path

from librus_python_api import LibrusService
from librus_python_api.exceptions import ErrorKind, LibrusError
from librus_python_api.files import prepare_attachment_directory
from librus_python_api.persistence import NotificationBootstrap, NotificationStore, PersistenceStore

from librus_mcp.config import AppConfig, ConfigError
from librus_mcp.runtime import notification_limits


async def diagnose(config: AppConfig, *, check_storage: bool = False) -> dict[str, object]:
    if check_storage:
        # Explicit diagnostic consent can provision the private parent. Never
        # open or advance the real native-v2 database or old JSON state.
        await prepare_attachment_directory(config.state_dir)
        try:
            with tempfile.TemporaryDirectory(prefix="doctor-", dir=config.state_dir) as directory:
                async with (
                    LibrusService(
                        {account.alias: account.credentials() for account in config.accounts},
                        context_key=config.key_bytes(),
                    ) as service,
                    NotificationStore(
                        Path(directory) / "diagnostic", limits=notification_limits()
                    ) as notifications,
                    PersistenceStore(Path(directory) / "diagnostic") as sends,
                ):
                    context = service.account(config.accounts[0].alias).context
                    await notifications.bootstrap(
                        NotificationBootstrap(context=context, mappings=(), pending_events=()),
                        context=context,
                    )
                    state = await notifications.state(context=context)
                    if not state.initialized or await sends.send_history(context=context):
                        raise LibrusError(ErrorKind.STORAGE)
        except OSError:
            raise ConfigError(
                "storage diagnostic or cleanup failed; inspect doctor directories"
            ) from None
    return {
        "status": "ok",
        "accounts": len(config.accounts),
        "features": config.features.model_dump(),
        "storage_checked": check_storage,
        "network": "not_attempted",
    }
