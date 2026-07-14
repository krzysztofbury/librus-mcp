"""Tests for per-alias NotificationIds persistence."""

import pytest
from librus_apix.notifications import NotificationIds

from src.notification_state import (
    load_notification_ids,
    resolve_state_dir,
    save_notification_ids,
)


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
