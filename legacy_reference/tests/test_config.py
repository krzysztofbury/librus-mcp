"""Tests for configuration validation and credential handling."""

import json
import os
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from src.config import (
    MAX_ALIAS_LENGTH,
    MAX_CONFIG_FILE_BYTES,
    AccountConfig,
    AppConfig,
    ConfigError,
    FeaturesConfig,
    load_config,
)


def _write_secure_config(path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)


class TestFeaturesConfig:
    def test_defaults(self):
        features = FeaturesConfig()
        assert features.notifications is True
        assert features.attachments is True
        assert features.behaviour_notes is False
        assert features.send_message is False

    def test_template_matches_feature_defaults(self):
        template = json.loads(
            (Path(__file__).parent.parent / "secrets.json.template").read_text(encoding="utf-8")
        )

        assert template["features"] == FeaturesConfig().model_dump()

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

    def test_state_dir_and_download_dir_have_expanded_defaults(self):
        config = AppConfig(accounts=[{"alias": "a", "username": "u", "password": "p"}])
        assert config.state_dir == Path.home() / ".librus-mcp" / "state"
        assert config.download_dir == Path.home() / ".librus-mcp" / "downloads"

    def test_explicit_null_paths_use_defaults(self):
        config = AppConfig(
            accounts=[{"alias": "a", "username": "u", "password": "p"}],
            state_dir=None,
            download_dir=None,
        )
        assert config.state_dir == Path.home() / ".librus-mcp" / "state"
        assert config.download_dir == Path.home() / ".librus-mcp" / "downloads"


class TestAccountValidation:
    def test_duplicate_alias_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="duplicate"):
            AppConfig(
                accounts=[
                    {
                        "alias": "kid",
                        "username": "u1",
                        "password": "p1",  # pragma: allowlist secret
                    },
                    {
                        "alias": "kid",
                        "username": "u2",
                        "password": "p2",  # pragma: allowlist secret
                    },
                ]
            )

    def test_blank_alias_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="alias"):
            AppConfig(accounts=[{"alias": "   ", "username": "u", "password": "p"}])

    def test_blank_password_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="password"):
            AppConfig(accounts=[{"alias": "kid", "username": "u", "password": ""}])

    def test_empty_accounts_raises(self):
        with pytest.raises(ValidationError, match="at least one"):
            AppConfig(accounts=[])

    def test_password_is_redacted_in_repr_and_dump(self):
        marker = "recognizable-password"  # pragma: allowlist secret
        account = AccountConfig(alias="kid", username="u", password=marker)

        assert isinstance(account.password, SecretStr)
        assert account.password.get_secret_value() == marker
        assert marker not in repr(account)
        assert marker not in repr(account.model_dump())

    def test_validation_error_hides_password(self):
        marker = "recognizable-password"  # pragma: allowlist secret

        with pytest.raises(ValidationError) as error:
            AppConfig(accounts=[{"username": "u", "password": marker}])

        assert marker not in str(error.value)

        with pytest.raises(ValidationError) as account_error:
            AccountConfig(alias="a", username="u", password=[marker])
        assert marker not in str(account_error.value)

    def test_unknown_account_key_raises(self):
        with pytest.raises(ValidationError, match="extra"):
            AccountConfig(alias="kid", username="u", password="p", usernme="typo")

    @pytest.mark.parametrize(
        "alias", [" kid", "kid ", "kid\nname", "kid\u00a0name", "kid\u2028name"]
    )
    def test_alias_with_surrounding_whitespace_or_control_character_raises(self, alias):
        with pytest.raises(ValidationError, match="alias"):
            AccountConfig(alias=alias, username="u", password="p")

    def test_alias_length_boundary(self):
        assert MAX_ALIAS_LENGTH == 80
        account = AccountConfig(alias="a" * MAX_ALIAS_LENGTH, username="u", password="p")
        assert len(account.alias) == MAX_ALIAS_LENGTH

        with pytest.raises(ValidationError, match="at most"):
            AccountConfig(alias="a" * (MAX_ALIAS_LENGTH + 1), username="u", password="p")


class TestLoadConfigFeatures:
    def test_explicit_path_overrides_environment_accounts(self, tmp_path, monkeypatch):
        secrets = tmp_path / "secrets.json"
        _write_secure_config(
            secrets,
            {"accounts": [{"alias": "file", "username": "u", "password": "p"}]},
        )
        monkeypatch.setenv(
            "LIBRUS_ACCOUNTS",
            json.dumps([{"alias": "environment", "username": "u", "password": "p"}]),
        )

        config = load_config(secrets)

        assert config.accounts[0].alias == "file"

    @pytest.mark.parametrize("environment_accounts", ["{not-json", "null"])
    def test_explicit_path_ignores_invalid_environment_accounts(
        self, tmp_path, monkeypatch, environment_accounts
    ):
        secrets = tmp_path / "secrets.json"
        _write_secure_config(
            secrets,
            {"accounts": [{"alias": "file", "username": "u", "password": "p"}]},
        )
        monkeypatch.setenv("LIBRUS_ACCOUNTS", environment_accounts)

        config = load_config(secrets)

        assert config.accounts[0].alias == "file"

    def test_null_env_accounts_does_not_fall_back_to_file(self, tmp_path, monkeypatch):
        secrets = tmp_path / "secrets.json"
        _write_secure_config(
            secrets,
            {"accounts": [{"alias": "file", "username": "u", "password": "p"}]},
        )
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))
        monkeypatch.setenv("LIBRUS_ACCOUNTS", "null")

        with pytest.raises(ConfigError, match="LIBRUS_ACCOUNTS.*not null"):
            load_config()

    def test_null_env_features_is_rejected(self, monkeypatch):
        monkeypatch.setenv(
            "LIBRUS_ACCOUNTS",
            json.dumps([{"alias": "a", "username": "u", "password": "p"}]),
        )
        monkeypatch.setenv("LIBRUS_FEATURES", "null")

        with pytest.raises(ConfigError, match="LIBRUS_FEATURES.*not null"):
            load_config()

    @pytest.mark.skipif(
        os.name != "posix", reason="environment names are case-insensitive on Windows"
    )
    def test_lowercase_environment_name_is_ignored(self, tmp_path, monkeypatch):
        secrets = tmp_path / "secrets.json"
        _write_secure_config(
            secrets,
            {"accounts": [{"alias": "file", "username": "u", "password": "p"}]},
        )
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))
        monkeypatch.setenv(
            "librus_accounts",
            json.dumps([{"alias": "lowercase", "username": "u", "password": "p"}]),
        )

        assert load_config().accounts[0].alias == "file"

    def test_env_accounts_wrong_type_raises_config_error(self, monkeypatch):
        monkeypatch.setenv("LIBRUS_ACCOUNTS", "{}")
        with pytest.raises(ConfigError, match="LIBRUS_ACCOUNTS.*valid list"):
            load_config()

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

    def test_features_env_wrong_type_raises_config_error(self, monkeypatch):
        monkeypatch.setenv(
            "LIBRUS_ACCOUNTS",
            json.dumps([{"alias": "a", "username": "u", "password": "p"}]),
        )
        monkeypatch.setenv("LIBRUS_FEATURES", "[]")
        with pytest.raises(ConfigError, match="LIBRUS_FEATURES.*valid dictionary"):
            load_config()

    def test_file_config_with_features(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        secrets = tmp_path / "secrets.json"
        _write_secure_config(
            secrets,
            {
                "accounts": [{"alias": "a", "username": "u", "password": "p"}],
                "features": {"send_message": True},
                "state_dir": str(tmp_path / "state"),
            },
        )
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))
        config = load_config()
        assert config.features.send_message is True
        assert config.state_dir == tmp_path / "state"

    def test_file_config_accepts_template_null_paths(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        secrets = tmp_path / "secrets.json"
        _write_secure_config(
            secrets,
            {
                "accounts": [{"alias": "a", "username": "u", "password": "p"}],
                "state_dir": None,
                "download_dir": None,
            },
        )
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))

        config = load_config()

        assert config.state_dir == Path.home() / ".librus-mcp" / "state"
        assert config.download_dir == Path.home() / ".librus-mcp" / "downloads"

    def test_file_config_empty_paths_keep_legacy_defaults(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        secrets = tmp_path / "secrets.json"
        _write_secure_config(
            secrets,
            {
                "accounts": [{"alias": "a", "username": "u", "password": "p"}],
                "state_dir": "",
                "download_dir": "",
            },
        )
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))

        config = load_config()

        assert config.state_dir == Path.home() / ".librus-mcp" / "state"
        assert config.download_dir == Path.home() / ".librus-mcp" / "downloads"

    def test_environment_paths_and_features_override_file_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        secrets = tmp_path / "secrets.json"
        _write_secure_config(
            secrets,
            {
                "accounts": [{"alias": "a", "username": "u", "password": "p"}],
                "features": {"send_message": True},
                "state_dir": str(tmp_path / "file-state"),
                "download_dir": str(tmp_path / "file-downloads"),
            },
        )
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))
        monkeypatch.setenv("LIBRUS_STATE_DIR", str(tmp_path / "env-state"))
        monkeypatch.setenv("LIBRUS_DOWNLOAD_DIR", str(tmp_path / "env-downloads"))
        monkeypatch.setenv("LIBRUS_FEATURES", '{"attachments": false}')

        config = load_config()

        assert config.state_dir == tmp_path / "env-state"
        assert config.download_dir == tmp_path / "env-downloads"
        assert config.features.attachments is False
        assert config.features.send_message is True

    def test_config_paths_expand_home(self, monkeypatch):
        monkeypatch.setenv(
            "LIBRUS_ACCOUNTS",
            json.dumps([{"alias": "a", "username": "u", "password": "p"}]),
        )
        monkeypatch.setenv("LIBRUS_STATE_DIR", "~/custom-state")
        monkeypatch.setenv("LIBRUS_DOWNLOAD_DIR", "~/custom-downloads")

        config = load_config()

        assert "~" not in str(config.state_dir)
        assert "~" not in str(config.download_dir)

    def test_file_config_wrong_type_raises_type_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        secrets = tmp_path / "secrets.json"
        _write_secure_config(secrets, [])
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))

        with pytest.raises(ConfigError, match="JSON object"):
            load_config()

    def test_env_validation_error_is_redacted(self, monkeypatch):
        marker = "env-recognizable-password"  # pragma: allowlist secret
        monkeypatch.setenv(
            "LIBRUS_ACCOUNTS",
            json.dumps([{"username": "u", "password": marker}]),
        )

        with pytest.raises(ConfigError) as error:
            load_config()

        assert marker not in str(error.value)
        assert "LIBRUS_ACCOUNTS.0.alias" in str(error.value)

    def test_file_validation_error_is_redacted(self, tmp_path, monkeypatch):
        marker = "file-recognizable-password"  # pragma: allowlist secret
        secrets = tmp_path / "secrets.json"
        _write_secure_config(secrets, {"accounts": [{"username": "u", "password": marker}]})
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))

        with pytest.raises(ConfigError) as error:
            load_config()

        assert marker not in str(error.value)
        assert "accounts.0.alias" in str(error.value)

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable")
    @pytest.mark.parametrize("mode", [0o640, 0o604, 0o601])
    def test_rejects_group_or_other_access_to_credential_file(self, tmp_path, monkeypatch, mode):
        secrets = tmp_path / "secrets.json"
        _write_secure_config(
            secrets,
            {"accounts": [{"alias": "a", "username": "u", "password": "p"}]},
        )
        secrets.chmod(mode)
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))

        with pytest.raises(ConfigError, match="chmod 600"):
            load_config()

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable")
    def test_accepts_private_credential_file(self, tmp_path, monkeypatch):
        secrets = tmp_path / "secrets.json"
        _write_secure_config(
            secrets,
            {"accounts": [{"alias": "a", "username": "u", "password": "p"}]},
        )
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))

        assert load_config().accounts[0].alias == "a"

    def test_rejects_invalid_utf8_credential_file(self, tmp_path, monkeypatch):
        secrets = tmp_path / "secrets.json"
        secrets.write_bytes(b"\xff\xfe")
        if os.name == "posix":
            secrets.chmod(0o600)
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))

        with pytest.raises(ConfigError, match="invalid UTF-8"):
            load_config()

    def test_rejects_oversized_credential_file(self, tmp_path, monkeypatch):
        assert MAX_CONFIG_FILE_BYTES == 1024 * 1024
        secrets = tmp_path / "secrets.json"
        secrets.write_bytes(b" " * (MAX_CONFIG_FILE_BYTES + 1))
        if os.name == "posix":
            secrets.chmod(0o600)
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))

        with pytest.raises(ConfigError, match="too large"):
            load_config()

    def test_accepts_credential_file_at_exact_size_limit(self, tmp_path, monkeypatch):
        data = json.dumps({"accounts": [{"alias": "a", "username": "u", "password": "p"}]})
        padding = " " * (MAX_CONFIG_FILE_BYTES - len(data.encode("utf-8")))
        secrets = tmp_path / "secrets.json"
        secrets.write_text(data + padding, encoding="utf-8")
        if os.name == "posix":
            secrets.chmod(0o600)
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))

        assert load_config().accounts[0].alias == "a"

    @pytest.mark.skipif(os.name != "posix", reason="FIFO semantics are POSIX-specific")
    def test_rejects_non_regular_credential_file_without_blocking(self, tmp_path, monkeypatch):
        secrets = tmp_path / "secrets.json"
        os.mkfifo(secrets, mode=0o600)
        monkeypatch.delenv("LIBRUS_ACCOUNTS", raising=False)
        monkeypatch.setenv("LIBRUS_CONFIG", str(secrets))

        with pytest.raises(ConfigError, match="regular file"):
            load_config()


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
