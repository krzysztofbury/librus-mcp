"""Tests for per-alias NotificationIds persistence."""

import hashlib
import json
import multiprocessing
import os
import stat
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from librus_apix.notifications import NotificationIds
from librus_apix.schedule import RecentEvent

from src import notification_state
from src.notification_state import (
    MAX_IDS_PER_CATEGORY,
    MAX_LEGACY_FILENAME_LENGTH,
    MAX_NOTIFICATION_ID_LENGTH,
    MAX_NOTIFICATION_STATE_FILE_BYTES,
    MAX_PENDING_SCHEDULE_BATCH_BYTES,
    MAX_PENDING_SCHEDULE_EVENT_BYTES,
    MAX_STATE_ALIAS_PREFIX_LENGTH,
    _state_path,
    clear_pending_schedule_events,
    load_notification_ids,
    load_pending_schedule_events,
    save_notification_ids,
    save_pending_schedule_events,
    schedule_event_id,
    verify_notification_state_storage,
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


def _empty_state_payload() -> dict[str, list[str]]:
    return {
        key: []
        for key in ("grades", "attendance", "messages", "announcements", "schedule", "homework")
    }


class TestSaveLoadRoundtrip:
    def test_storage_verification_exercises_state_and_lock_without_leaving_files(self, tmp_path):
        verify_notification_state_storage(tmp_path)

        assert tmp_path.is_dir()
        assert list(tmp_path.iterdir()) == []

    def test_storage_verification_attempts_file_cleanup_after_lock_release_failure(self, tmp_path):
        original_release = notification_state.release_notification_state_lock

        def release_then_fail(descriptor):
            original_release(descriptor)
            raise OSError("release failed")

        with (
            patch.object(
                notification_state,
                "release_notification_state_lock",
                side_effect=release_then_fail,
            ),
            pytest.raises(OSError, match="release failed"),
        ):
            verify_notification_state_storage(tmp_path)

        assert list(tmp_path.iterdir()) == []

    def test_roundtrip(self, tmp_path):
        save_notification_ids(tmp_path, "primary", _sample_ids())
        loaded = load_notification_ids(tmp_path, "primary")
        assert loaded is not None
        assert loaded.grades == ["/g/1", "/g/2"]
        assert loaded.messages == ["123456"]
        assert loaded.homework == ["/hw/1"]

    def test_save_creates_nested_state_directory(self, tmp_path):
        state_dir = tmp_path / "nested" / "state"

        save_notification_ids(state_dir, "primary", _sample_ids())

        assert load_notification_ids(state_dir, "primary") is not None

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable")
    def test_state_directory_and_file_are_private_with_permissive_umask(self, tmp_path):
        state_dir = tmp_path / "nested" / "state"
        previous_umask = os.umask(0)
        try:
            save_notification_ids(state_dir, "primary", _sample_ids())
        finally:
            os.umask(previous_umask)

        state_path = _state_path(state_dir, "primary")
        assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(state_path.stat().st_mode) == 0o600

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable")
    def test_created_state_modes_override_restrictive_umask(self, tmp_path):
        state_dir = tmp_path / "state"
        try:
            previous_umask = os.umask(0o777)
            try:
                save_notification_ids(state_dir, "primary", _sample_ids())
            finally:
                os.umask(previous_umask)

            state_path = _state_path(state_dir, "primary")
            assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
            assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
        finally:
            if state_dir.exists():
                state_dir.chmod(0o700)

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable")
    @pytest.mark.parametrize("mode", [0o755, 0o600, 0o300, 0o000])
    def test_repairs_existing_owned_state_directory_with_wrong_mode(self, tmp_path, mode):
        state_dir = tmp_path / "state"
        state_dir.mkdir(mode=mode)
        state_dir.chmod(mode)

        save_notification_ids(state_dir, "primary", _sample_ids())

        assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
        assert load_notification_ids(state_dir, "primary") is not None

    @pytest.mark.skipif(os.name != "posix", reason="POSIX ownership is not portable")
    @pytest.mark.parametrize("mode", [0o700, 0o755])
    def test_rejects_state_directory_not_owned_by_current_user(self, tmp_path, monkeypatch, mode):
        state_dir = tmp_path / "state"
        state_dir.mkdir(mode=mode)
        state_dir.chmod(mode)
        monkeypatch.setattr(os, "geteuid", lambda: state_dir.stat().st_uid + 1)

        with pytest.raises(PermissionError, match="owned by the current user"):
            save_notification_ids(state_dir, "primary", _sample_ids())

        assert stat.S_IMODE(state_dir.stat().st_mode) == mode

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable")
    def test_reports_when_state_directory_cannot_be_repaired(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir(mode=0o755)
        state_dir.chmod(0o755)

        with (
            patch("src.notification_state.os.fchmod", side_effect=OSError("denied")),
            pytest.raises(PermissionError, match="could not be secured automatically"),
        ):
            notification_state._ensure_state_directory(state_dir)

        assert stat.S_IMODE(state_dir.stat().st_mode) == 0o755

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable")
    def test_reports_when_unreadable_state_directory_cannot_be_repaired(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir(mode=0o000)
        state_dir.chmod(0o000)

        try:
            with (
                patch("src.notification_state.os.chmod", side_effect=OSError("denied")),
                pytest.raises(PermissionError, match="could not be secured automatically"),
            ):
                notification_state._ensure_state_directory(state_dir)
        finally:
            state_dir.chmod(0o700)

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable")
    def test_does_not_repair_unreadable_state_directory_in_shared_parent(self, tmp_path):
        shared_dir = tmp_path / "shared"
        shared_dir.mkdir(mode=0o777)
        shared_dir.chmod(0o777)
        state_dir = shared_dir / "state"
        state_dir.mkdir(mode=0o000)
        state_dir.chmod(0o000)

        try:
            with pytest.raises(PermissionError, match="could not be secured automatically"):
                notification_state._ensure_state_directory(state_dir)

            assert stat.S_IMODE(state_dir.stat().st_mode) == 0o000
        finally:
            state_dir.chmod(0o700)
            shared_dir.chmod(0o700)

    @pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks are not portable")
    def test_rejects_symlinked_state_directory(self, tmp_path):
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        state_dir = tmp_path / "state"
        state_dir.symlink_to(target, target_is_directory=True)

        with pytest.raises(ValueError, match="symlink"):
            save_notification_ids(state_dir, "primary", _sample_ids())

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable")
    def test_legacy_state_mirror_is_private(self, tmp_path):
        save_notification_ids(tmp_path, "child/a", _sample_ids())

        state_files = list(tmp_path.glob("*.notifications.json"))
        assert len(state_files) == 2
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in state_files)

    def test_missing_file_returns_none(self, tmp_path):
        assert load_notification_ids(tmp_path, "nobody") is None

    def test_corrupt_file_returns_none(self, tmp_path):
        save_notification_ids(tmp_path, "primary", _sample_ids())
        # Corrupt the file on disk.
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        files[0].write_text("{not valid json")
        assert load_notification_ids(tmp_path, "primary") is None

    def test_scalar_category_returns_none(self, tmp_path):
        data = _empty_state_payload()
        data["grades"] = "not-a-list"
        _state_path(tmp_path, "primary").write_text(json.dumps(data), encoding="utf-8")

        assert load_notification_ids(tmp_path, "primary") is None

    @pytest.mark.parametrize(
        "data",
        [
            [],
            {"grades": []},
            {
                "grades": [],
                "attendance": [],
                "messages": [],
                "announcements": [],
                "schedule": [],
                "homework": [],
                "unexpected": [],
            },
        ],
    )
    def test_unexpected_top_level_schema_returns_none(self, tmp_path, data):
        _state_path(tmp_path, "primary").write_text(json.dumps(data), encoding="utf-8")

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

    def test_new_version_imports_lexically_smaller_legacy_payload(self, tmp_path):
        alias = "child/a"
        empty_ids = NotificationIds([], [], [], [], [], [])
        save_notification_ids(tmp_path, alias, empty_ids)
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
        assert legacy_path.read_bytes() < _state_path(tmp_path, alias).read_bytes()

        loaded = load_notification_ids(tmp_path, alias)

        assert loaded is not None
        assert loaded.grades == ids.grades

    def test_long_sanitized_alias_stays_within_filename_limit(self, tmp_path):
        assert MAX_STATE_ALIAS_PREFIX_LENGTH == 80
        assert MAX_LEGACY_FILENAME_LENGTH == 190
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

    def test_oversized_state_file_is_rejected_before_json_parse(self, tmp_path, capsys):
        assert MAX_NOTIFICATION_STATE_FILE_BYTES == 4 * 1024 * 1024
        path = _state_path(tmp_path, "primary")
        path.write_bytes(b" " * (MAX_NOTIFICATION_STATE_FILE_BYTES + 1))

        assert load_notification_ids(tmp_path, "primary") is None
        assert "too large" in capsys.readouterr().err

    def test_state_file_at_exact_size_limit_is_accepted(self, tmp_path):
        data = json.dumps(_empty_state_payload()).encode("utf-8")
        path = _state_path(tmp_path, "primary")
        path.write_bytes(data + b" " * (MAX_NOTIFICATION_STATE_FILE_BYTES - len(data)))

        assert load_notification_ids(tmp_path, "primary") is not None

    @pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks are not portable")
    def test_symlinked_state_file_is_not_read(self, tmp_path):
        target = tmp_path / "target.json"
        target.write_text(json.dumps(_empty_state_payload()), encoding="utf-8")
        _state_path(tmp_path, "primary").symlink_to(target)

        assert load_notification_ids(tmp_path, "primary") is None

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are not portable")
    def test_fifo_state_file_is_rejected_without_blocking(self, tmp_path):
        os.mkfifo(_state_path(tmp_path, "primary"))

        assert load_notification_ids(tmp_path, "primary") is None

    def test_oversized_category_is_rejected_on_load(self, tmp_path):
        data = _empty_state_payload()
        data["grades"] = ["x"] * (MAX_IDS_PER_CATEGORY + 1)
        _state_path(tmp_path, "primary").write_text(json.dumps(data), encoding="utf-8")

        assert load_notification_ids(tmp_path, "primary") is None

    @pytest.mark.parametrize("invalid_id", [1, None, [], {}, ""])
    def test_invalid_notification_id_is_rejected_on_load(self, tmp_path, invalid_id):
        data = _empty_state_payload()
        data["grades"] = [invalid_id]
        _state_path(tmp_path, "primary").write_text(json.dumps(data), encoding="utf-8")

        assert load_notification_ids(tmp_path, "primary") is None

    def test_notification_id_length_boundary_on_load(self, tmp_path):
        assert MAX_NOTIFICATION_ID_LENGTH == 1024
        data = _empty_state_payload()
        data["grades"] = ["x" * MAX_NOTIFICATION_ID_LENGTH]
        path = _state_path(tmp_path, "primary")
        path.write_text(json.dumps(data), encoding="utf-8")
        assert load_notification_ids(tmp_path, "primary") is not None

        data["grades"] = ["x" * (MAX_NOTIFICATION_ID_LENGTH + 1)]
        path.write_text(json.dumps(data), encoding="utf-8")
        assert load_notification_ids(tmp_path, "primary") is None


class TestPendingScheduleEvents:
    def test_save_creates_nested_state_directory(self, tmp_path):
        state_dir = tmp_path / "nested" / "spool"
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")

        save_pending_schedule_events(state_dir, "primary", [event])

        assert load_pending_schedule_events(state_dir, "primary") == [event]

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable")
    def test_spool_directory_and_file_are_private_with_permissive_umask(self, tmp_path):
        state_dir = tmp_path / "nested" / "spool"
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        previous_umask = os.umask(0)
        try:
            save_pending_schedule_events(state_dir, "primary", [event])
        finally:
            os.umask(previous_umask)

        path = next(state_dir.glob("*.pending-schedule.*.json"))
        assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_roundtrip_is_content_addressed_and_clear_is_exact(self, tmp_path):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka 2026-09-20")
        later_event = RecentEvent("2026-09-15 09:00", "Wycieczka", "Muzeum")

        save_pending_schedule_events(tmp_path, "primary", [event, later_event])
        save_pending_schedule_events(tmp_path, "primary", [event])

        assert set(map(schedule_event_id, load_pending_schedule_events(tmp_path, "primary"))) == {
            schedule_event_id(event),
            schedule_event_id(later_event),
        }
        assert len(list(tmp_path.glob("*.pending-schedule.*.json"))) == 2
        clear_pending_schedule_events(tmp_path, "primary", [event])
        assert load_pending_schedule_events(tmp_path, "primary") == [later_event]

    def test_event_at_exact_file_size_limit_is_accepted(self, tmp_path, monkeypatch):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        encoded_size = len(notification_state._encoded_schedule_event(event)) + 2
        monkeypatch.setattr(notification_state, "MAX_PENDING_SCHEDULE_EVENT_BYTES", encoded_size)

        save_pending_schedule_events(tmp_path, "exact", [event])
        assert load_pending_schedule_events(tmp_path, "exact") == [event]

        monkeypatch.setattr(
            notification_state, "MAX_PENDING_SCHEDULE_EVENT_BYTES", encoded_size - 1
        )
        with pytest.raises(ValueError, match="too large"):
            save_pending_schedule_events(tmp_path, "oversize", [event])

    def test_load_batch_byte_limit_accepts_exact_boundary(self, tmp_path, monkeypatch):
        events = [
            RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka"),
            RecentEvent("2026-09-15 09:00", "Sprawdzian", "Fizyka"),
            RecentEvent("2026-09-15 10:00", "Sprawdzian", "Chemia"),
        ]
        exact_size = (
            2
            + sum(len(notification_state._encoded_schedule_event(event)) for event in events)
            + len(events)
            - 1
        )
        monkeypatch.setattr(notification_state, "MAX_PENDING_SCHEDULE_BATCH_BYTES", exact_size)

        save_pending_schedule_events(tmp_path, "primary", events)
        assert len(list(tmp_path.glob("*.pending-schedule.*.json"))) == 1
        assert load_pending_schedule_events(tmp_path, "primary") == events

        monkeypatch.setattr(notification_state, "MAX_PENDING_SCHEDULE_BATCH_BYTES", exact_size - 1)
        loaded = load_pending_schedule_events(tmp_path, "primary")
        assert len(loaded) == 2
        assert loaded[0] in events

    def test_load_accepts_exact_event_count_across_files(self, tmp_path, monkeypatch):
        events = [
            RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka"),
            RecentEvent("2026-09-15 09:00", "Sprawdzian", "Fizyka"),
        ]
        save_pending_schedule_events(tmp_path, "primary", [events[0]])
        save_pending_schedule_events(tmp_path, "primary", [events[1]])
        monkeypatch.setattr(notification_state, "MAX_PENDING_SCHEDULE_EVENTS", 2)
        exact_size = (
            2 + sum(len(notification_state._encoded_schedule_event(event)) for event in events) + 1
        )
        monkeypatch.setattr(notification_state, "MAX_PENDING_SCHEDULE_BATCH_BYTES", exact_size)

        loaded = load_pending_schedule_events(tmp_path, "primary")
        assert set(map(schedule_event_id, loaded)) == set(map(schedule_event_id, events))

        monkeypatch.setattr(notification_state, "MAX_PENDING_SCHEDULE_BATCH_BYTES", exact_size - 1)
        assert len(load_pending_schedule_events(tmp_path, "primary")) == 1

        monkeypatch.setattr(notification_state, "MAX_PENDING_SCHEDULE_BATCH_BYTES", exact_size)
        monkeypatch.setattr(notification_state, "MAX_PENDING_SCHEDULE_EVENTS", 1)
        assert len(load_pending_schedule_events(tmp_path, "primary")) == 1

    def test_complete_batch_file_size_boundary(self, tmp_path, monkeypatch):
        events = [
            RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka"),
            RecentEvent("2026-09-15 09:00", "Sprawdzian", "Fizyka"),
        ]
        encoded = [notification_state._encoded_schedule_event(event) for event in events]
        exact_size = 2 + sum(map(len, encoded)) + 1
        monkeypatch.setattr(notification_state, "MAX_PENDING_SCHEDULE_EVENT_BYTES", exact_size)

        save_pending_schedule_events(tmp_path, "exact", events)
        path = next(tmp_path.glob("exact*.pending-schedule.batch.*.json"))
        assert path.stat().st_size == exact_size

        monkeypatch.setattr(notification_state, "MAX_PENDING_SCHEDULE_EVENT_BYTES", exact_size - 1)
        with pytest.raises(ValueError, match="batch is too large"):
            save_pending_schedule_events(tmp_path, "oversize", events)
        assert not list(tmp_path.glob("oversize*.pending-schedule.*.json"))

    def test_batch_publication_failure_exposes_no_partial_checkpoint(self, tmp_path):
        events = [
            RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka"),
            RecentEvent("2026-09-15 09:00", "Sprawdzian", "Fizyka"),
        ]

        with (
            patch.object(notification_state, "_atomic_publish", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            save_pending_schedule_events(tmp_path, "primary", events)

        assert not list(tmp_path.glob("*.pending-schedule.*.json"))

    def test_legacy_single_event_spool_loads_and_clears(self, tmp_path):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        path = notification_state._pending_schedule_path(tmp_path, "primary", event)
        path.write_bytes(notification_state._encoded_schedule_event(event))

        assert load_pending_schedule_events(tmp_path, "primary") == [event]
        clear_pending_schedule_events(tmp_path, "primary", [event])
        assert not path.exists()

    def test_spool_encoding_is_canonical_utf8(self):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "żółć")

        assert notification_state._encoded_schedule_event(event) == (
            b'{"data":"\xc5\xbc\xc3\xb3\xc5\x82\xc4\x87","date_added":"2026-09-15 08:00",'
            b'"type":"Sprawdzian"}'
        )

    def test_clear_without_legacy_file_is_silent(self, tmp_path, capsys):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")

        clear_pending_schedule_events(tmp_path, "primary", [event])

        assert capsys.readouterr().err == ""

    def test_clear_fsyncs_only_nonempty_cleanup(self, tmp_path):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")

        with patch.object(notification_state, "_fsync_directory") as fsync:
            clear_pending_schedule_events(tmp_path, "primary", [])
            fsync.assert_not_called()
            clear_pending_schedule_events(tmp_path, "primary", [event])
            fsync.assert_called_once_with(tmp_path)

    def test_clear_reports_legacy_unlink_error_without_failing(self, tmp_path, capsys):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")

        with patch.object(Path, "unlink", side_effect=OSError("unlink failed")):
            clear_pending_schedule_events(tmp_path, "primary", [event])

        assert "unlink failed" in capsys.readouterr().err

    def test_clear_reports_fsync_error_without_failing(self, tmp_path, capsys):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")

        with patch.object(
            notification_state, "_fsync_directory", side_effect=OSError("fsync failed")
        ):
            clear_pending_schedule_events(tmp_path, "primary", [event])

        assert "fsync failed" in capsys.readouterr().err

    @pytest.mark.parametrize("error", [OSError("io"), TypeError("type"), ValueError("value")])
    def test_clear_reports_batch_errors_without_failing(self, tmp_path, capsys, error):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        save_pending_schedule_events(tmp_path, "primary", [event])

        with patch.object(notification_state, "_pending_events_from_file", side_effect=error):
            clear_pending_schedule_events(tmp_path, "primary", [event])

        assert str(error) in capsys.readouterr().err

    def test_batch_disappearing_during_clear_is_silent(self, tmp_path, capsys):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        save_pending_schedule_events(tmp_path, "primary", [event])

        original_reader = notification_state._pending_events_from_file

        def removing_reader(batch_path, state_dir, alias):
            result = original_reader(batch_path, state_dir, alias)
            batch_path.unlink()
            return result

        with patch.object(notification_state, "_pending_events_from_file", removing_reader):
            clear_pending_schedule_events(tmp_path, "primary", [event])

        assert capsys.readouterr().err == ""

    def test_clearing_unrelated_event_preserves_batch(self, tmp_path):
        spooled = [
            RecentEvent(f"2026-09-15 08:{index:03}", "Sprawdzian", "Matematyka")
            for index in range(257)
        ]
        unrelated = RecentEvent("2026-09-16 08:00", "Sprawdzian", "Fizyka")
        save_pending_schedule_events(tmp_path, "primary", spooled)

        clear_pending_schedule_events(tmp_path, "primary", [unrelated])

        assert load_pending_schedule_events(tmp_path, "primary") == spooled

    def test_identity_covers_all_visible_fields(self):
        first = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        second = RecentEvent("2026-09-16 08:00", "Sprawdzian", "Matematyka")

        assert schedule_event_id(first) != schedule_event_id(second)

    def test_identity_uses_canonical_unicode_json(self):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "żółć")
        canonical = '{"data":"żółć","date_added":"2026-09-15 08:00","type":"Sprawdzian"}'

        assert schedule_event_id(event) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def test_corrupt_spool_fails_loudly(self, tmp_path):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        save_pending_schedule_events(tmp_path, "primary", [event])
        path = next(tmp_path.glob("*.pending-schedule.*.json"))
        path.write_text("{not-json", encoding="utf-8")

        with pytest.raises(ValueError, match="corrupt pending schedule"):
            load_pending_schedule_events(tmp_path, "primary")

    def test_oversized_spool_fails_before_json_parse(self, tmp_path):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        save_pending_schedule_events(tmp_path, "primary", [event])
        path = next(tmp_path.glob("*.pending-schedule.*.json"))
        path.write_bytes(b" " * (MAX_PENDING_SCHEDULE_EVENT_BYTES + 1))

        with pytest.raises(ValueError, match="too large"):
            load_pending_schedule_events(tmp_path, "primary")

    def test_large_pending_schedule_save_is_preserved_and_drains_across_loads(self, tmp_path):
        data = "x" * (MAX_PENDING_SCHEDULE_BATCH_BYTES // 3)
        events = [
            RecentEvent(f"2026-09-{index + 10} 08:00", "Sprawdzian", data) for index in range(4)
        ]

        save_pending_schedule_events(tmp_path, "primary", events)
        first_batch = load_pending_schedule_events(tmp_path, "primary")
        assert 0 < len(first_batch) < len(events)
        clear_pending_schedule_events(tmp_path, "primary", first_batch)
        second_batch = load_pending_schedule_events(tmp_path, "primary")
        assert set(map(schedule_event_id, first_batch + second_batch)) == set(
            map(schedule_event_id, events)
        )

    @pytest.mark.parametrize(
        "payload",
        [
            [],
            {"date_added": "2026-09-15 08:00"},
            {
                "date_added": "2026-09-15 08:00",
                "type": "Sprawdzian",
                "data": "Matematyka",
                "unexpected": "field",
            },
        ],
    )
    def test_unexpected_spool_schema_fails_loudly(self, tmp_path, payload):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        save_pending_schedule_events(tmp_path, "primary", [event])
        path = next(tmp_path.glob("*.pending-schedule.*.json"))
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError, match="unexpected pending schedule event schema"):
            load_pending_schedule_events(tmp_path, "primary")

    def test_large_spool_is_drained_in_bounded_batches(self, tmp_path):
        events = [
            RecentEvent(f"2026-09-15 {index:04d}", "Sprawdzian", f"Matematyka {index}")
            for index in range(501)
        ]

        save_pending_schedule_events(tmp_path, "primary", events)
        assert len(list(tmp_path.glob("*.pending-schedule.*.json"))) == 1
        first_batch = load_pending_schedule_events(tmp_path, "primary")
        assert 0 < len(first_batch) <= 500

        clear_pending_schedule_events(tmp_path, "primary", first_batch)
        second_batch = load_pending_schedule_events(tmp_path, "primary")
        assert set(map(schedule_event_id, first_batch + second_batch)) == set(
            map(schedule_event_id, events)
        )

    def test_event_larger_than_processing_batch_is_still_preserved(self, tmp_path):
        event = RecentEvent(
            "2026-09-15 08:00",
            "Sprawdzian",
            "x" * (MAX_PENDING_SCHEDULE_BATCH_BYTES + 1),
        )

        save_pending_schedule_events(tmp_path, "primary", [event])

        assert load_pending_schedule_events(tmp_path, "primary") == [event]

    def test_rejects_non_string_event_fields(self, tmp_path):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", 123)

        with pytest.raises(TypeError, match="data must be a string"):
            save_pending_schedule_events(tmp_path, "primary", [event])

    def test_valid_tampered_payload_fails_digest_check(self, tmp_path):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        save_pending_schedule_events(tmp_path, "primary", [event])
        path = next(tmp_path.glob("*.pending-schedule.*.json"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload[0]["data"] = "Fizyka"
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError, match="digest mismatch"):
            load_pending_schedule_events(tmp_path, "primary")

    @pytest.mark.parametrize("replacement_digest", ["0" * 64, "f" * 64])
    def test_batch_filename_digest_must_match_in_both_sort_directions(
        self, tmp_path, replacement_digest
    ):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        save_pending_schedule_events(tmp_path, "primary", [event])
        path = next(tmp_path.glob("*.pending-schedule.batch.*.json"))
        parts = path.name.split(".")
        parts[-2] = replacement_digest
        path.rename(path.with_name(".".join(parts)))

        with pytest.raises(ValueError, match="digest mismatch"):
            load_pending_schedule_events(tmp_path, "primary")

    @pytest.mark.parametrize("replacement_digest", ["0" * 64, "f" * 64])
    def test_legacy_filename_digest_must_match_in_both_sort_directions(
        self, tmp_path, replacement_digest
    ):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        valid_path = notification_state._pending_schedule_path(tmp_path, "primary", event)
        parts = valid_path.name.split(".")
        parts[-2] = replacement_digest
        valid_path.with_name(".".join(parts)).write_bytes(
            notification_state._encoded_schedule_event(event)
        )

        with pytest.raises(ValueError, match="digest mismatch"):
            load_pending_schedule_events(tmp_path, "primary")

    def test_tampered_payload_fails_digest_check_in_opposite_sort_order(self, tmp_path):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        original_id = schedule_event_id(event)
        tampered_event = None
        for index in range(100):
            candidate = RecentEvent("2026-09-15 08:00", "Sprawdzian", f"tampered-{index}")
            if schedule_event_id(candidate) < original_id:
                tampered_event = candidate
                break
        assert tampered_event is not None, "test must cover the opposite digest ordering"
        save_pending_schedule_events(tmp_path, "primary", [event])
        path = next(tmp_path.glob("*.pending-schedule.*.json"))
        path.write_text(
            json.dumps(
                {
                    "date_added": tampered_event.date_added,
                    "type": tampered_event.type,
                    "data": tampered_event.data,
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="digest mismatch"):
            load_pending_schedule_events(tmp_path, "primary")


class TestProcessStateLock:
    def test_lock_creates_nested_state_directory(self, tmp_path):
        from src.notification_state import (
            release_notification_state_lock,
            try_acquire_notification_state_lock,
        )

        descriptor = try_acquire_notification_state_lock(tmp_path / "nested" / "state", "primary")
        assert descriptor is not None
        release_notification_state_lock(descriptor)

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable")
    def test_lock_directory_and_file_are_private_with_permissive_umask(self, tmp_path):
        from src.notification_state import (
            release_notification_state_lock,
            try_acquire_notification_state_lock,
        )

        state_dir = tmp_path / "nested" / "state"
        previous_umask = os.umask(0)
        try:
            descriptor = try_acquire_notification_state_lock(state_dir, "primary")
        finally:
            os.umask(previous_umask)
        assert descriptor is not None
        release_notification_state_lock(descriptor)

        lock_path = next(state_dir.glob("*.lock"))
        assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600

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
    def test_category_size_limit_accepts_boundary_and_rejects_oversize(self, tmp_path):
        assert MAX_IDS_PER_CATEGORY == 10_000
        boundary_ids = NotificationIds(
            grades=[f"/g/{index}" for index in range(10_000)],
            attendance=[],
            messages=[],
            announcements=[],
            schedule=[],
            homework=[],
        )
        save_notification_ids(tmp_path, "boundary", boundary_ids)

        boundary_ids.grades.append("/g/oversize")
        with pytest.raises(ValueError, match="unexpectedly large"):
            save_notification_ids(tmp_path, "oversize", boundary_ids)

    @pytest.mark.parametrize("invalid_id", [1, None, [], {}, "", "x" * 1025])
    def test_save_rejects_invalid_notification_ids(self, tmp_path, invalid_id):
        ids = NotificationIds([invalid_id], [], [], [], [], [])

        with pytest.raises((TypeError, ValueError), match="notification ID"):
            save_notification_ids(tmp_path, "invalid", ids)

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
