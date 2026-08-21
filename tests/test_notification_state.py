"""Tests for per-alias NotificationIds persistence."""

import hashlib
import json
import multiprocessing
import threading
import time
from pathlib import Path

import pytest
from librus_apix.notifications import NotificationIds

from src.notification_state import (
    _state_path,
    load_notification_ids,
    resolve_state_dir,
    save_notification_ids,
)


def _hold_notification_lock(
    state_dir: str,
    alias: str,
    locked,
    release,
) -> None:
    """Keep a process-level state lock until the parent releases this worker."""
    from src.notification_state import release_notification_state_lock

    descriptor = _wait_for_notification_lock(Path(state_dir), alias)
    try:
        locked.set()
        release.wait(timeout=5)
    finally:
        release_notification_state_lock(descriptor)


def _wait_for_notification_lock(state_dir: Path, alias: str) -> int:
    from src.notification_state import try_acquire_notification_state_lock

    for _ in range(500):
        descriptor = try_acquire_notification_state_lock(state_dir, alias)
        if descriptor is not None:
            return descriptor
        time.sleep(0.01)
    raise TimeoutError("notification lock was not acquired during the test")


def _sample_ids() -> NotificationIds:
    return NotificationIds(
        grades=["/g/1", "/g/2"],
        attendance=["/a/1"],
        messages=["123456"],
        announcements=["Title2026-01-01"],
        schedule=["abcdef0123"],
        homework=["/hw/1"],
    )


class TestSaveLoadRoundtrip:
    def test_roundtrip(self, tmp_path):
        save_notification_ids(tmp_path, "primary", _sample_ids())
        loaded = load_notification_ids(tmp_path, "primary")
        assert loaded is not None
        assert loaded.grades == ["/g/1", "/g/2"]
        assert loaded.messages == ["123456"]
        assert loaded.homework == ["/hw/1"]

    def test_missing_file_returns_none(self, tmp_path):
        assert load_notification_ids(tmp_path, "nobody") is None

    def test_corrupt_file_returns_none(self, tmp_path):
        save_notification_ids(tmp_path, "primary", _sample_ids())
        # Corrupt the file on disk.
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        files[0].write_text("{not valid json")
        assert load_notification_ids(tmp_path, "primary") is None

    def test_alias_with_spaces_and_slashes_is_sanitized(self, tmp_path):
        save_notification_ids(tmp_path, "Parent A/../x", _sample_ids())
        # No file may escape the state dir.
        for path in tmp_path.rglob("*"):
            assert tmp_path in path.parents
        loaded = load_notification_ids(tmp_path, "Parent A/../x")
        assert loaded is not None

    def test_sanitized_alias_uses_full_sha256_digest(self, tmp_path):
        alias = "child/a"
        expected_digest = hashlib.sha256(alias.encode("utf-8")).hexdigest()

        save_notification_ids(tmp_path, alias, _sample_ids())

        assert _state_path(tmp_path, alias).name == (
            f"child_a.{expected_digest}.notifications.json"
        )
        assert len(expected_digest) == 64

    def test_legacy_short_digest_state_is_migrated_on_load(self, tmp_path):
        alias = "child/a"
        short_digest = hashlib.sha256(alias.encode("utf-8")).hexdigest()[:8]
        legacy_path = tmp_path / f"child_a.{short_digest}.notifications.json"
        ids = _sample_ids()
        legacy_path.write_text(
            json.dumps(
                {
                    key: getattr(ids, key)
                    for key in (
                        "grades",
                        "attendance",
                        "messages",
                        "announcements",
                        "schedule",
                        "homework",
                    )
                }
            ),
            encoding="utf-8",
        )

        loaded = load_notification_ids(tmp_path, alias)

        assert loaded is not None
        assert loaded.grades == ids.grades
        assert _state_path(tmp_path, alias).exists()
        assert legacy_path.exists()
        assert legacy_path.read_bytes() == _state_path(tmp_path, alias).read_bytes()

    def test_new_version_imports_updates_written_by_old_version(self, tmp_path):
        alias = "child/a"
        save_notification_ids(tmp_path, alias, _sample_ids())
        short_digest = hashlib.sha256(alias.encode("utf-8")).hexdigest()[:8]
        legacy_path = tmp_path / f"child_a.{short_digest}.notifications.json"
        old_process_ids = NotificationIds([], [], ["new-message"], [], [], [])
        legacy_path.write_text(
            json.dumps(
                {
                    key: getattr(old_process_ids, key)
                    for key in (
                        "grades",
                        "attendance",
                        "messages",
                        "announcements",
                        "schedule",
                        "homework",
                    )
                }
            ),
            encoding="utf-8",
        )

        loaded = load_notification_ids(tmp_path, alias)

        assert loaded is not None
        assert loaded.messages == ["new-message"]
        assert legacy_path.read_bytes() == _state_path(tmp_path, alias).read_bytes()

    def test_long_sanitized_alias_stays_within_filename_limit(self, tmp_path):
        alias = f"{'a' * 200}/child"

        save_notification_ids(tmp_path, alias, _sample_ids())

        assert len(_state_path(tmp_path, alias).name.encode("utf-8")) < 200
        assert load_notification_ids(tmp_path, alias).grades == ["/g/1", "/g/2"]

    def test_aliases_do_not_collide(self, tmp_path):
        ids_a = _sample_ids()
        ids_b = NotificationIds([], [], [], [], [], [])
        save_notification_ids(tmp_path, "primary", ids_a)
        save_notification_ids(tmp_path, "secondary", ids_b)
        assert load_notification_ids(tmp_path, "primary").grades == ["/g/1", "/g/2"]
        assert load_notification_ids(tmp_path, "secondary").grades == []

    def test_aliases_sanitizing_to_same_name_do_not_collide(self, tmp_path):
        """'child/a' and 'child?a' both sanitize to 'child_a'; their state
        files must stay distinct or notifications would cross accounts."""
        ids_a = _sample_ids()
        ids_b = NotificationIds([], [], [], [], [], [])
        save_notification_ids(tmp_path, "child/a", ids_a)
        save_notification_ids(tmp_path, "child?a", ids_b)
        assert load_notification_ids(tmp_path, "child/a").grades == ["/g/1", "/g/2"]
        assert load_notification_ids(tmp_path, "child?a").grades == []

    def test_sanitized_alias_does_not_shadow_literal_alias(self, tmp_path):
        ids_literal = _sample_ids()
        ids_sanitized = NotificationIds([], [], [], [], [], [])
        save_notification_ids(tmp_path, "child_a", ids_literal)
        save_notification_ids(tmp_path, "child/a", ids_sanitized)
        assert load_notification_ids(tmp_path, "child_a").grades == ["/g/1", "/g/2"]
        assert load_notification_ids(tmp_path, "child/a").grades == []

    def test_empty_alias_raises(self, tmp_path):
        with pytest.raises(AssertionError):
            save_notification_ids(tmp_path, "", _sample_ids())


class TestResolveStateDir:
    def test_env_var_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LIBRUS_STATE_DIR", str(tmp_path / "env_state"))
        result = resolve_state_dir(str(tmp_path / "config_state"))
        assert result == tmp_path / "env_state"

    def test_config_value_used_when_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LIBRUS_STATE_DIR", raising=False)
        result = resolve_state_dir(str(tmp_path / "config_state"))
        assert result == tmp_path / "config_state"

    def test_default_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("LIBRUS_STATE_DIR", raising=False)
        result = resolve_state_dir(None)
        assert result.name == "state"
        assert ".librus-mcp" in str(result)

    def test_tilde_in_config_value_is_expanded(self, monkeypatch):
        monkeypatch.delenv("LIBRUS_STATE_DIR", raising=False)
        result = resolve_state_dir("~/custom_state")
        assert "~" not in str(result)
        assert str(result).startswith("/")


class TestProcessStateLock:
    def test_sanitized_alias_uses_legacy_lock_name_during_migration(self, tmp_path):
        from src.notification_state import (
            release_notification_state_lock,
            try_acquire_notification_state_lock,
        )

        alias = "child/a"
        short_digest = hashlib.sha256(alias.encode("utf-8")).hexdigest()[:8]
        descriptor = try_acquire_notification_state_lock(tmp_path, alias)
        assert descriptor is not None
        try:
            assert (tmp_path / f"child_a.{short_digest}.notifications.json.lock").exists()
        finally:
            release_notification_state_lock(descriptor)

    def test_second_process_waits_for_notification_transaction(self, tmp_path):
        from src.notification_state import release_notification_state_lock

        context = multiprocessing.get_context("spawn")
        first_locked = context.Event()
        release_first = context.Event()
        second_locked = threading.Event()
        first_process = context.Process(
            target=_hold_notification_lock,
            args=(str(tmp_path), "primary", first_locked, release_first),
        )
        first_process.start()
        # A cold Python interpreter can take several seconds to spawn and
        # import the test module in CI; this is process startup, not lock work.
        assert first_locked.wait(timeout=30)

        def acquire_second_lock() -> None:
            descriptor = _wait_for_notification_lock(tmp_path, "primary")
            try:
                second_locked.set()
            finally:
                release_notification_state_lock(descriptor)

        second_thread = threading.Thread(target=acquire_second_lock)
        second_thread.start()
        try:
            assert not second_locked.wait(timeout=0.1)
        finally:
            release_first.set()
            first_process.join(timeout=5)
            second_thread.join(timeout=5)
        assert first_process.exitcode == 0
        assert second_locked.is_set()


class TestPruning:
    def test_ids_pruned_to_newest_500_on_save(self, tmp_path):
        ids = NotificationIds(
            grades=[f"/g/{i}" for i in range(600)],
            attendance=[],
            messages=[],
            announcements=[],
            schedule=[],
            homework=[],
        )
        save_notification_ids(tmp_path, "primary", ids)
        loaded = load_notification_ids(tmp_path, "primary")
        assert len(loaded.grades) == 500
        # Most recently appended IDs (the tail) must survive pruning.
        assert loaded.grades[0] == "/g/100"
        assert loaded.grades[-1] == "/g/599"
