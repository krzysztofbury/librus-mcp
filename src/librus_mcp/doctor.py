"""Offline application diagnostics using disposable public native storage only."""

import secrets
import tempfile
from pathlib import Path

from librus_python_api import LibrusService
from librus_python_api.exceptions import ErrorKind, LibrusError
from librus_python_api.persistence import NotificationBootstrap, NotificationStore, PersistenceStore

from librus_mcp.config import AppConfig, ConfigError
from librus_mcp.runtime import notification_limits, prepare_private_directory


async def diagnose(config: AppConfig, *, check_storage: bool = False) -> dict[str, object]:
    if check_storage:
        # Explicit diagnostic consent can provision the private parent. Never
        # open or advance the real native-v2 database or old JSON state.
        await prepare_private_directory(config.state_dir)
        try:
            with tempfile.TemporaryDirectory(prefix="doctor-", dir=config.state_dir) as directory:
                async with (
                    LibrusService(
                        {account.alias: account.credentials() for account in config.accounts},
                        # A disposable probe needs no persistent key; never create one here.
                        context_key=config.key_bytes()
                        if config.context_key is not None
                        else secrets.token_bytes(32),
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
