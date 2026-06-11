"""Tests for the features section of the configuration."""

import json

import pytest

from src.config import AppConfig, FeaturesConfig, load_config


class TestFeaturesConfig:
    def test_defaults(self):
        features = FeaturesConfig()
        assert features.notifications is True
        assert features.attachments is True
        assert features.behaviour_notes is True
        assert features.send_message is False

    def test_app_config_defaults_features(self):
        config = AppConfig(accounts=[{"alias": "a", "username": "u", "password": "p"}])
        assert config.features.notifications is True
        assert config.features.send_message is False

    def test_features_from_dict(self):
        config = AppConfig(
            accounts=[{"alias": "a", "username": "u", "password": "p"}],
            features={"notifications": False, "send_message": True},
        )
        assert config.features.notifications is False
        assert config.features.send_message is True
        # Unspecified keys keep defaults.
        assert config.features.attachments is True

    def test_state_dir_and_download_dir_default_none(self):
        config = AppConfig(accounts=[{"alias": "a", "username": "u", "password": "p"}])
        assert config.state_dir is None
        assert config.download_dir is None


class TestLoadConfigFeatures:
    def test_env_accounts_with_features_env(self, monkeypatch):
        monkeypatch.setenv(
            "LIBRUS_ACCOUNTS",
            json.dumps([{"alias": "a", "username": "u", "password": "p"}]),
        )
        monkeypatch.setenv("LIBRUS_FEATURES", json.dumps({"attachments": False}))
        config = load_config()
        assert config.features.attachments is False
        assert config.features.notifications is True

    def test_features_env_invalid_json_raises(self, monkeypatch):
        monkeypatch.setenv(
            "LIBRUS_ACCOUNTS",
            json.dumps([{"alias": "a", "username": "u", "password": "p"}]),
        )
        monkeypatch.setenv("LIBRUS_FEATURES", "{not json")
        with pytest.raises(ValueError, match="LIBRUS_FEATURES"):
            load_config()

    def test_file_config_with_features(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        secrets = tmp_path / "secrets.json"
        secrets.write_text(
            json.dumps(
                {
                    "accounts": [{"alias": "a", "username": "u", "password": "p"}],
                    "features": {"send_message": True},
                    "state_dir": str(tmp_path / "state"),
                }
            )
        )
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))
        config = load_config()
        assert config.features.send_message is True
        assert config.state_dir == str(tmp_path / "state")


class TestUnknownFeatureKeys:
    def test_features_env_unknown_key_raises(self, monkeypatch):
        monkeypatch.setenv(
            "LIBRUS_ACCOUNTS",
            json.dumps([{"alias": "a", "username": "u", "password": "p"}]),
        )
        # Trailing 's' typo must not be silently ignored — it gates a write action.
        monkeypatch.setenv("LIBRUS_FEATURES", json.dumps({"send_messages": True}))
        with pytest.raises(ValueError, match="unknown"):
            load_config()

    def test_features_dict_unknown_key_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AppConfig(
                accounts=[{"alias": "a", "username": "u", "password": "p"}],
                features={"send_messagez": True},
            )

    def test_app_config_unknown_top_level_key_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AppConfig(
                accounts=[{"alias": "a", "username": "u", "password": "p"}],
                downloads_dir="/tmp",
            )
