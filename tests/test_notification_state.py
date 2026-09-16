"""Tests for per-alias NotificationIds persistence."""

import hashlib
import json
import multiprocessing
import os
import stat
import threading
import time
from pathlib import Path

import pytest
from librus_apix.notifications import NotificationIds
from librus_apix.schedule import RecentEvent

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
    @pytest.mark.parametrize("mode", [0o755, 0o600])
    def test_rejects_existing_state_directory_with_wrong_mode(self, tmp_path, mode):
        state_dir = tmp_path / "state"
        state_dir.mkdir(mode=mode)
        state_dir.chmod(mode)

        with pytest.raises(PermissionError, match="chmod 700"):
            save_notification_ids(state_dir, "primary", _sample_ids())

        assert stat.S_IMODE(state_dir.stat().st_mode) == mode

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

    def test_pending_schedule_batch_size_is_bounded_and_drains_across_loads(self, tmp_path):
        data = "x" * (MAX_PENDING_SCHEDULE_BATCH_BYTES // 3)
        events = [
            RecentEvent(f"2026-09-{index + 10} 08:00", "Sprawdzian", data) for index in range(4)
        ]

        with pytest.raises(ValueError, match="batch is too large"):
            save_pending_schedule_events(tmp_path, "primary", events)
        assert not list(tmp_path.glob("*.pending-schedule.*.json"))

        for event in events:
            save_pending_schedule_events(tmp_path, "primary", [event])
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
        first_batch = load_pending_schedule_events(tmp_path, "primary")
        assert len(first_batch) == 500

        clear_pending_schedule_events(tmp_path, "primary", first_batch)
        assert len(load_pending_schedule_events(tmp_path, "primary")) == 1

    def test_rejects_non_string_event_fields(self, tmp_path):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", 123)

        with pytest.raises(TypeError, match="data must be a string"):
            save_pending_schedule_events(tmp_path, "primary", [event])

    def test_valid_tampered_payload_fails_digest_check(self, tmp_path):
        event = RecentEvent("2026-09-15 08:00", "Sprawdzian", "Matematyka")
        save_pending_schedule_events(tmp_path, "primary", [event])
        path = next(tmp_path.glob("*.pending-schedule.*.json"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["data"] = "Fizyka"
        path.write_text(json.dumps(payload), encoding="utf-8")

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
