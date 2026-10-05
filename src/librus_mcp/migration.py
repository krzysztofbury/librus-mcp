"""Explicit offline old-state bootstrap through public native contracts only."""

import base64
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from librus_python_api import LibrusService, NotificationCategory
from librus_python_api.files import prepare_attachment_directory
from librus_python_api.persistence import (
    NotificationBaselineMapping,
    NotificationBootstrap,
    NotificationStore,
)
from pydantic import Field, ValidationError

from librus_mcp import __version__
from librus_mcp.config import AppConfig, ConfigError
from librus_mcp.legacy_state import inventory_legacy, legacy_stems, migration_json, private_bytes
from librus_mcp.read_schemas import AccountAliasInput, HexDigest
from librus_mcp.runtime import notification_limits
from librus_mcp.schemas import WireModel


class BaselineMappingInput(WireModel):
    category: NotificationCategory
    source_identifier: Annotated[str, Field(min_length=1, max_length=256)]
    native_identifier: HexDigest | None
    # A consumer/operator records how the native ID was independently established;
    # this is not cryptographic proof or permission to hash an old opaque ID.
    evidence: Annotated[str, Field(min_length=1, max_length=2048)]


class MigrationMappingInput(WireModel):
    account_alias: AccountAliasInput
    context: HexDigest
    source_files: dict[str, HexDigest]
    mappings: Annotated[tuple[BaselineMappingInput, ...], Field(max_length=24576)]


def _publish_manifest(path: Path, payload: object) -> None:
    # Exclusive, private and fsynced. A partial manifest is retained on error;
    # native state must be inspected, not blindly bootstrapped again.
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as file:
            descriptor = -1
            file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
            file.flush()
            os.fsync(file.fileno())
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except OSError, ValueError:
        raise ConfigError(
            "cannot publish migration manifest; inspect target before retrying"
        ) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


async def migrate_state(
    config: AppConfig,
    *,
    source_dir: Path,
    account_alias: str,
    mapping_file: Path | None = None,
    apply: bool = False,
    writers_stopped: bool = False,
    binding_reviewed: bool = False,
) -> dict[str, object]:
    if not source_dir.is_absolute() or source_dir == config.state_dir:
        raise ConfigError(
            "select an absolute legacy source separate from the native state directory"
        )
    aliases = {account.alias for account in config.accounts}
    if account_alias not in aliases:
        raise ConfigError("migration account is not configured")
    stems = set(legacy_stems(account_alias))
    if any(stems.intersection(legacy_stems(alias)) for alias in aliases if alias != account_alias):
        raise ConfigError("legacy filename collision between configured accounts")
    inventory = inventory_legacy(source_dir, account_alias)
    report: dict[str, object] = {
        "mode": "apply" if apply else "dry_run",
        "source_files": len(inventory.files),
        "baseline_ids": len(inventory.baseline),
        "pending_events": len(inventory.pending_events),
        "mapped_ids": 0,
        "unmapped_ids": len(inventory.baseline),
        "imported": False,
    }
    if mapping_file is None:
        if apply:
            raise ConfigError("apply requires an explicit reviewed mapping plan")
        return report
    try:
        mapping = MigrationMappingInput.model_validate(
            migration_json(private_bytes(mapping_file, 4 * 1024 * 1024))
        )
    except ValidationError:
        raise ConfigError("invalid migration mapping plan") from None
    if mapping.account_alias != account_alias or mapping.source_files != inventory.files:
        raise ConfigError("mapping plan account or source fingerprints do not match")
    mapped_keys = [(entry.category, entry.source_identifier) for entry in mapping.mappings]
    if len(set(mapped_keys)) != len(mapped_keys) or set(mapped_keys) != set(inventory.baseline):
        raise ConfigError("mapping plan must cover each source baseline ID exactly once")
    native_keys = [
        (entry.category, entry.native_identifier)
        for entry in mapping.mappings
        if entry.native_identifier is not None
    ]
    if len(set(native_keys)) != len(native_keys):
        raise ConfigError("colliding native baseline mappings")
    unmapped = sum(entry.native_identifier is None for entry in mapping.mappings)
    report.update(mapped_ids=len(mapping.mappings) - unmapped, unmapped_ids=unmapped)
    async with LibrusService(
        {account.alias: account.credentials() for account in config.accounts},
        context_key=config.key_bytes(),
    ) as service:
        context = service.account(account_alias).context
        if context.identifier != mapping.context:
            raise ConfigError("mapping plan is bound to a different native login context")
        if not apply:
            return report
        if unmapped or not writers_stopped or not binding_reviewed:
            raise ConfigError(
                "apply requires fully mapped IDs, stopped writers and reviewed login binding"
            )
        await prepare_attachment_directory(config.state_dir)
        target = config.state_dir / "native-v2"
        # Same bounds as serving; no private SQL, codec or native archive parsing.
        async with NotificationStore(target, limits=notification_limits()) as store:
            status = await store.recovery_status(context=context)
            if status.initialized or status.has_pending_work:
                raise ConfigError("migration target context is not empty")
            if inventory_legacy(source_dir, account_alias) != inventory:
                raise ConfigError("legacy source changed during review; stop all writers")
            _publish_manifest(
                target / f"migration-{context.identifier}.prepared.json",
                {
                    "mcp_version": __version__,
                    "context": context.identifier,
                    "source_dir": str(source_dir),
                    "target_dir": str(target),
                    "mapping": mapping.model_dump(mode="json"),
                },
            )
            plan = NotificationBootstrap(
                context=context,
                mappings=tuple(
                    NotificationBaselineMapping(
                        category=entry.category,
                        source_identifier=entry.source_identifier,
                        native_identifier=entry.native_identifier,
                    )
                    for entry in mapping.mappings
                ),
                pending_events=inventory.pending_events,
            )
            result = await store.bootstrap(plan, context=context)
            if not result.imported:
                raise ConfigError("native bootstrap rejected the mapping; originals remain intact")
            _publish_manifest(
                target / f"migration-{context.identifier}.completed.json",
                {
                    "imported": True,
                    "pending_receipt": None if result.pending is None else result.pending.receipt,
                },
            )
            report["imported"] = True
    return report


async def notification_state(
    config: AppConfig,
    *,
    account_alias: str,
    export_file: Path | None = None,
    resolve_uncertain: bool = False,
    accept_possible_loss: bool = False,
) -> dict[str, object]:
    """Offline recovery/export only; no transparent downgrade or implicit pruning."""
    if os.name != "posix":
        raise ConfigError("operator recovery files require a qualified POSIX host")
    if account_alias not in {account.alias for account in config.accounts}:
        raise ConfigError("recovery account is not configured")
    if export_file is not None and not export_file.is_absolute():
        raise ConfigError("archive destination must be absolute")
    if resolve_uncertain and not accept_possible_loss:
        raise ConfigError(
            "uncertainty resolution requires explicit acceptance of possible event loss"
        )
    target = config.state_dir / "native-v2"
    if not target.is_dir():
        raise ConfigError("native state directory does not exist")
    async with (
        LibrusService(
            {account.alias: account.credentials() for account in config.accounts},
            context_key=config.key_bytes(),
        ) as service,
        NotificationStore(target, limits=notification_limits()) as store,
    ):
        context = service.account(account_alias).context
        if resolve_uncertain:
            await store.resolve_uncertain_consume(
                context=context, accept_possible_loss=accept_possible_loss
            )
        if export_file is not None:
            archive = await store.export_archive(context=context)
            await prepare_attachment_directory(export_file.parent)
            _publish_manifest(
                export_file,
                {
                    "format": "librus-mcp/native-notification-archive/v1",
                    "mcp_version": __version__,
                    "version": archive.version,
                    "context": asdict(archive.context),
                    "payload_base64": base64.b64encode(archive.payload).decode("ascii"),
                },
            )
        status = await store.recovery_status(context=context)
        return {
            "initialized": status.initialized,
            "has_pending_work": status.has_pending_work,
            "pending_items": None if status.pending is None else status.pending.item_count,
            "raw_checkpoint": status.raw is not None,
            "uncertain_consume": status.uncertain_consume,
            "archive_exported": export_file is not None,
            "uncertainty_resolved": resolve_uncertain,
        }
