"""Original old-format sources -> public bootstrap -> real MCP replay/ack."""

import base64
import hashlib
import json
import os
import subprocess
import sys

import anyio
import pytest
from librus_python_api import LibrusService, NotificationCategory, RecentScheduleEvent
from librus_python_api.persistence import (
    NotificationArchive,
    NotificationStore,
    canonical_notification_id,
)
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from librus_mcp.cli import main
from librus_mcp.config import load_config
from librus_mcp.migration import migrate_state, notification_state
from tests_native.test_config import config_data, write_config

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="old-file no-follow migration is POSIX-only"
)


def migration_files(tmp_path, *, batch=True):
    source = tmp_path / "old"
    source.mkdir(mode=0o700)
    state = tmp_path / "native"
    data = config_data() | {"state_dir": str(state), "features": {"notifications": True}}
    data["accounts"][0].update(
        alias="account",
        username="71",
        password="not-a-real-password",  # pragma: allowlist secret - synthetic credentials only
    )
    config = tmp_path / "config.json"
    write_config(config, data)
    baseline = source / "account.notifications.json"
    values = {
        category: []
        for category in (
            "grades",
            "attendance",
            "messages",
            "announcements",
            "schedule",
            "homework",
        )
    }
    baseline.write_text(json.dumps(values | {"schedule": ["old-seen-event-id"]}))
    baseline.chmod(0o600)
    event = {
        "date_added": "2026-09-26 10:00",
        "type": "Fixture history",
        "data": "Preserved event text",
    }
    body = json.dumps(
        [event] if batch else event, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    kind = "batch." if batch else ""
    pending = source / f"account.pending-schedule.{kind}{hashlib.sha256(body).hexdigest()}.json"
    pending.write_bytes(body)
    pending.chmod(0o600)
    return source, state, config, event


def cli_args(config, source, mode="--dry-run", mapping=None):
    result = [
        "--config",
        str(config),
        "migrate-state",
        mode,
        "--source-dir",
        str(source),
        "--account-alias",
        "account",
    ]
    if mapping is not None:
        result += ["--mapping-file", str(mapping)]
    if mode == "--apply":
        result += ["--confirm-writers-stopped", "--confirm-login-binding-reviewed"]
    return result


def test_inventory_is_offline_read_only_and_reports_unmapped_ids(tmp_path, capsys):
    source, state, config, _ = migration_files(tmp_path)
    originals = {path.name: path.read_bytes() for path in source.iterdir()}
    main(cli_args(config, source))
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "mode": "dry_run",
        "source_files": 2,
        "baseline_ids": 1,
        "pending_events": 1,
        "mapped_ids": 0,
        "unmapped_ids": 1,
        "imported": False,
    }
    assert not state.exists()
    assert {path.name: path.read_bytes() for path in source.iterdir()} == originals
    with pytest.raises(SystemExit):
        main(cli_args(config, source, "--apply"))
    assert not state.exists()


@pytest.mark.parametrize(
    "fault",
    [
        "corrupt",
        "duplicate_json",
        "invalid_unicode",
        "wrong_digest",
        "duplicate_events",
        "shared",
        "symlink",
    ],
)
def test_bad_inventory_fails_without_reset_or_target_write(tmp_path, capsys, fault):
    source, state, config, _ = migration_files(tmp_path)
    baseline = source / "account.notifications.json"
    if fault == "corrupt":
        baseline.write_bytes(b"private malformed state")
    elif fault == "duplicate_json":
        baseline.write_bytes(b'{"grades":[],"grades":[]}')
    elif fault == "invalid_unicode":
        baseline.write_bytes(baseline.read_bytes().replace(b'"old-seen-event-id"', b'"\\ud800"'))
    elif fault == "wrong_digest":
        pending = next(source.glob("*.pending-schedule*"))
        pending.rename(source / ("account.pending-schedule.batch." + "0" * 64 + ".json"))
    elif fault == "duplicate_events":
        pending = next(source.glob("*.pending-schedule*"))
        events = json.loads(pending.read_bytes()) * 2
        body = json.dumps(events, sort_keys=True, separators=(",", ":")).encode()
        pending.unlink()
        (
            source / f"account.pending-schedule.batch.{hashlib.sha256(body).hexdigest()}.json"
        ).write_bytes(body)
        next(source.glob("*.pending-schedule*")).chmod(0o600)
    elif fault == "shared":
        baseline.chmod(0o644)
    else:
        other = source / "original.json"
        baseline.rename(other)
        baseline.symlink_to(other)
    with pytest.raises(SystemExit) as error:
        main(cli_args(config, source))
    assert error.value.code == 1 and not state.exists()
    output = capsys.readouterr()
    assert (
        output.out == ""
        and "private malformed state" not in output.err
        and "Traceback" not in output.err
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_reviewed_bootstrap_preserves_originals_and_history_replays_offline_after_restart(
    tmp_path,
    batch,
):
    source, state, config, event = migration_files(tmp_path, batch=batch)
    settings = load_config(config)
    async with LibrusService(
        {account.alias: account.credentials() for account in settings.accounts},
        context_key=settings.key_bytes(),
    ) as service:
        context = service.account("account").context.identifier
    seen = RecentScheduleEvent(
        date_added="2026-09-25", type="Other history", data="Previously delivered"
    )
    mapping = tmp_path / "mapping.json"
    plan = {
        "account_alias": "account",
        "context": context,
        "source_files": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.iterdir()
        },
        "mappings": [
            {
                "category": "agenda",
                "source_identifier": "old-seen-event-id",
                "native_identifier": canonical_notification_id(NotificationCategory.AGENDA, seen),
                "evidence": "Original synthetic event retained independently for identity mapping",
            }
        ],
    }
    mapping.write_text(json.dumps(plan))
    mapping.chmod(0o600)
    originals = {path.name: path.read_bytes() for path in source.iterdir()}
    environment = {key: value for key, value in os.environ.items() if not key.startswith("LIBRUS_")}
    environment.update(
        {
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1",
            "NO_PROXY": "",
        }
    )
    # Each of these fails at the mapping/approval boundary before target creation.
    for change in (
        {"context": "0" * 64},
        {"source_files": {}},
        {"mappings": []},
        {"mappings": [plan["mappings"][0] | {"native_identifier": None}]},
    ):
        mapping.write_text(json.dumps(plan | change))
        rejected = subprocess.run(
            [sys.executable, "-m", "librus_mcp.cli", *cli_args(config, source, "--apply", mapping)],
            capture_output=True,
            text=True,
            env=environment,
            timeout=20,
            check=False,
        )
        assert rejected.returncode == 1 and not state.exists()
    mapping.write_text(json.dumps(plan))
    unconfirmed = cli_args(config, source, "--apply", mapping)[:-2]
    rejected = subprocess.run(
        [sys.executable, "-m", "librus_mcp.cli", *unconfirmed],
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
        check=False,
    )
    assert rejected.returncode == 1 and not state.exists()
    for mode in ("--dry-run", "--apply"):
        completed = subprocess.run(
            [sys.executable, "-m", "librus_mcp.cli", *cli_args(config, source, mode, mapping)],
            capture_output=True,
            text=True,
            env=environment,
            timeout=20,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout)["imported"] is (mode == "--apply")
    assert {path.name: path.read_bytes() for path in source.iterdir()} == originals
    assert len(list((state / "native-v2").glob("migration-*.json"))) == 2
    # Repeat cannot overwrite an initialized target or its durable pending receipt.
    repeated = subprocess.run(
        [sys.executable, "-m", "librus_mcp.cli", *cli_args(config, source, "--apply", mapping)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
        check=False,
    )
    assert repeated.returncode == 1 and "not empty" in repeated.stderr
    archive_file = tmp_path / "native-export.json"
    recovery = [
        sys.executable,
        "-m",
        "librus_mcp.cli",
        "--config",
        str(config),
        "notification-state",
        "--account-alias",
        "account",
    ]
    exported = subprocess.run(
        [*recovery, "--export-file", str(archive_file)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
        check=False,
    )
    assert exported.returncode == 0 and json.loads(exported.stdout)["pending_items"] == 1
    assert archive_file.stat().st_mode & 0o077 == 0
    retained = archive_file.read_bytes()
    duplicate_export = subprocess.run(
        [*recovery, "--export-file", str(archive_file)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
        check=False,
    )
    assert duplicate_export.returncode == 1 and archive_file.read_bytes() == retained
    loss_rejected = subprocess.run(
        [*recovery, "--resolve-uncertain-consume"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
        check=False,
    )
    assert loss_rejected.returncode == 1 and "acceptance" in loss_rejected.stderr
    exported_data = json.loads(retained)
    async with (
        LibrusService(
            {account.alias: account.credentials() for account in settings.accounts},
            context_key=settings.key_bytes(),
        ) as service,
        NotificationStore(tmp_path / "recovery-copy") as store,
    ):
        account_context = service.account("account").context
        assert exported_data["context"] == {
            "alias": account_context.alias,
            "identifier": account_context.identifier,
        }
        await store.import_archive(
            NotificationArchive(
                version=exported_data["version"],
                context=account_context,
                payload=base64.b64decode(exported_data["payload_base64"]),
            )
        )
        pending = await store.pending_batch(context=account_context)
        assert pending is not None and pending.items[0].value == RecentScheduleEvent(**event)
    # Account context binds source origins as well as login/key. Use the real
    # CLI's default origins for offline replay, with all socket connects denied.
    script = """from unittest.mock import patch
from librus_mcp.cli import main
with patch('socket.socket.connect', side_effect=AssertionError('offline recovery attempted network')):
    main()
"""
    process = StdioServerParameters(
        command=sys.executable, args=["-c", script, "--config", str(config)], env=environment
    )
    with anyio.fail_after(20):
        async with stdio_client(process) as streams, ClientSession(*streams) as session:
            await session.initialize()
            status = await session.call_tool(
                "get_notification_status", {"account_alias": "account"}
            )
            assert not status.is_error and status.structured_content["has_pending_work"]
            replay = await session.call_tool(
                "get_new_notifications", {"account_alias": "account", "categories": ["agenda"]}
            )
            assert not replay.is_error, replay
            payload = replay.structured_content["data"]
            assert payload["first_run"] is False and payload["items"][0]["value"] == event
            assert payload["items"][0]["provenance"] == "imported_history"
            assert (
                payload["items"][0]["identity"] is None
                and payload["items"][0]["observation"] is None
            )
        async with stdio_client(process) as streams, ClientSession(*streams) as session:
            await session.initialize()
            replay = await session.call_tool(
                "get_new_notifications", {"account_alias": "account", "categories": ["agenda"]}
            )
            assert replay.structured_content["data"] == payload
            ack = await session.call_tool(
                "acknowledge_notifications",
                {"account_alias": "account", "receipt": payload["receipt"], "context": context},
            )
            assert not ack.is_error
            status = await session.call_tool(
                "get_notification_status", {"account_alias": "account"}
            )
            assert not status.structured_content["has_pending_work"]
    assert {path.name: path.read_bytes() for path in source.iterdir()} == originals


def test_full_hash_and_short_mirror_require_identical_baselines(tmp_path, capsys):
    source, state, config, _ = migration_files(tmp_path)
    data = json.loads(config.read_bytes())
    data["accounts"][0]["alias"] = "a/b"
    write_config(config, data)
    digest = hashlib.sha256(b"a/b").hexdigest()
    stem = f"a_b.{digest}"
    baseline = source / "account.notifications.json"
    contents = baseline.read_bytes()
    baseline.rename(source / f"{stem}.notifications.json")
    pending = next(source.glob("account.pending-schedule*"))
    pending.rename(source / pending.name.replace("account.", stem + ".", 1))
    mirror = source / f"a_b.{digest[:8]}.notifications.json"
    mirror.write_bytes(contents)
    mirror.chmod(0o600)
    arguments = cli_args(config, source)
    arguments[arguments.index("--account-alias") + 1] = "a/b"
    main(arguments)
    assert json.loads(capsys.readouterr().out)["source_files"] == 3
    assert not state.exists()
    mirror.write_text(json.dumps(json.loads(contents) | {"grades": ["conflicting-history"]}))
    with pytest.raises(SystemExit):
        main(arguments)
    assert "conflicting" in capsys.readouterr().err and not state.exists()


async def empty_baseline_mapping(source, config, tmp_path):
    baseline = source / "account.notifications.json"
    baseline.write_text(json.dumps({key: [] for key in json.loads(baseline.read_bytes())}))
    settings = load_config(config)
    async with LibrusService(
        {account.alias: account.credentials() for account in settings.accounts},
        context_key=settings.key_bytes(),
    ) as service:
        context = service.account("account").context
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "account_alias": "account",
                "context": context.identifier,
                "source_files": {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in source.iterdir()
                },
                "mappings": [],
            }
        )
    )
    mapping.chmod(0o600)
    return settings, mapping, context


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_completed", [False, True])
async def test_interrupted_manifest_preserves_source_and_exposes_target_recovery(
    tmp_path, monkeypatch, commit_completed
):
    from librus_mcp import migration
    from librus_mcp.config import ConfigError

    source, state, config, _ = migration_files(tmp_path)
    settings, mapping, context = await empty_baseline_mapping(source, config, tmp_path)
    originals = {path.name: path.read_bytes() for path in source.iterdir()}
    publish = migration._publish_manifest

    def interrupted(path, payload):
        if path.name.endswith(".completed.json") or not commit_completed:
            raise ConfigError("synthetic manifest interruption")
        publish(path, payload)

    with monkeypatch.context() as patch:
        patch.setattr(migration, "_publish_manifest", interrupted)
        with pytest.raises(ConfigError, match="interruption"):
            await migrate_state(
                settings,
                source_dir=source,
                account_alias="account",
                mapping_file=mapping,
                apply=True,
                writers_stopped=True,
                binding_reviewed=True,
            )
    async with NotificationStore(state / "native-v2") as store:
        status = await store.recovery_status(context=context)
        assert status.initialized is commit_completed
        assert status.has_pending_work is commit_completed
    if commit_completed:
        assert len(list((state / "native-v2").glob("*.prepared.json"))) == 1
        archive = tmp_path / "recovery.json"
        result = await notification_state(settings, account_alias="account", export_file=archive)
        assert result["pending_items"] == 1 and archive.exists()
        with pytest.raises(ConfigError, match="not empty"):
            await migrate_state(
                settings,
                source_dir=source,
                account_alias="account",
                mapping_file=mapping,
                apply=True,
                writers_stopped=True,
                binding_reviewed=True,
            )
    else:
        result = await migrate_state(
            settings,
            source_dir=source,
            account_alias="account",
            mapping_file=mapping,
            apply=True,
            writers_stopped=True,
            binding_reviewed=True,
        )
        assert result["imported"] is True
    assert {path.name: path.read_bytes() for path in source.iterdir()} == originals


@pytest.mark.asyncio
async def test_import_over_consumer_capacity_retains_all_original_events_without_target_write(
    tmp_path,
):
    from librus_mcp.config import ConfigError

    source, state, config, event = migration_files(tmp_path)
    pending = next(source.glob("*.pending-schedule*"))
    pending.unlink()
    body = json.dumps(
        [event | {"data": f"Retained event {index}"} for index in range(129)],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    pending = source / f"account.pending-schedule.batch.{hashlib.sha256(body).hexdigest()}.json"
    pending.write_bytes(body)
    pending.chmod(0o600)
    settings, mapping, _ = await empty_baseline_mapping(source, config, tmp_path)
    originals = {path.name: path.read_bytes() for path in source.iterdir()}
    with pytest.raises(ConfigError, match="batch item limit"):
        await migrate_state(
            settings,
            source_dir=source,
            account_alias="account",
            mapping_file=mapping,
            apply=True,
            writers_stopped=True,
            binding_reviewed=True,
        )
    assert not state.exists()
    assert {path.name: path.read_bytes() for path in source.iterdir()} == originals


def test_cross_account_filename_collision_is_rejected_before_target_creation(tmp_path, capsys):
    source, state, config, _ = migration_files(tmp_path)
    data = json.loads(config.read_bytes())
    # Independently found synthetic aliases: both sanitize to a___ and their
    # historical eight-hex SHA256 mirrors collide at b1cfc064.
    data["accounts"][0]["alias"] = "a/Эӆ"
    data["accounts"].append(data["accounts"][0] | {"alias": "a/ГЎ"})
    write_config(config, data)
    arguments = cli_args(config, source)
    arguments[arguments.index("--account-alias") + 1] = "a/Эӆ"
    with pytest.raises(SystemExit):
        main(arguments)
    assert "collision" in capsys.readouterr().err and not state.exists()
