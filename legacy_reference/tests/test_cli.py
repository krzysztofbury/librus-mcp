import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src import __version__


def _set_accounts(monkeypatch, password: str = "safe-password") -> None:
    monkeypatch.setenv(
        "LIBRUS_ACCOUNTS",
        json.dumps(
            [
                {
                    "alias": "test_student",
                    "username": "private-username",
                    "password": password,
                }
            ]
        ),
    )


class TestCliRouting:
    def test_no_arguments_starts_mcp_server(self):
        from src.cli import main

        with patch("src.server.main") as server_main:
            main([])

        server_main.assert_called_once_with()

    def test_explicit_config_path_starts_server_with_that_config(self, tmp_path, monkeypatch):
        from src.cli import main
        from src.librus_client import LibrusManager

        _set_accounts(monkeypatch, "environment-secret")
        config_path = tmp_path / "secrets.json"
        config_path.write_text(
            json.dumps(
                {
                    "accounts": [
                        {"alias": "from-file", "username": "file-user", "password": "file-secret"}
                    ]
                }
            ),
            encoding="utf-8",
        )
        if os.name == "posix":
            config_path.chmod(0o600)

        with patch("src.server.main") as server_main:
            main(["--config", str(config_path)])

        assert LibrusManager._config_cache is not None
        assert [account.alias for account in LibrusManager._config_cache.accounts] == ["from-file"]
        server_main.assert_called_once_with()

    def test_version_does_not_load_configuration(self, capsys):
        from src.cli import main

        with (
            patch("src.cli.load_config") as load_config,
            pytest.raises(SystemExit) as exit_error,
        ):
            main(["--version"])

        captured = capsys.readouterr()
        assert exit_error.value.code == 0
        assert captured.out == f"librus-mcp {__version__}\n"
        assert captured.err == ""
        load_config.assert_not_called()

    def test_help_lists_end_user_diagnostics(self, capsys):
        from src.cli import main

        with pytest.raises(SystemExit) as exit_error:
            main(["--help"])

        captured = capsys.readouterr()
        assert exit_error.value.code == 0
        assert "--check-config" in captured.out
        assert "doctor" in captured.out
        assert captured.err == ""


class TestCheckConfig:
    def test_valid_config_reports_only_safe_summary(self, monkeypatch, capsys):
        from src.cli import main

        password = "check-config-secret"  # pragma: allowlist secret
        _set_accounts(monkeypatch, password)

        with patch("socket.socket.connect") as network_connect:
            main(["--check-config"])

        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "[OK] Configuration is valid." in captured.out
        assert "1 account configured" in captured.out
        assert "private-username" not in output
        assert password not in output
        network_connect.assert_not_called()

    def test_explicit_config_path_overrides_environment_accounts(
        self, tmp_path, monkeypatch, capsys
    ):
        from src.cli import main

        _set_accounts(monkeypatch, "environment-secret")
        config_path = tmp_path / "secrets.json"
        config_path.write_text(
            json.dumps(
                {
                    "accounts": [
                        {"alias": "from-file", "username": "file-user", "password": "file-secret"}
                    ]
                }
            ),
            encoding="utf-8",
        )
        if os.name == "posix":
            config_path.chmod(0o600)

        main(["--config", str(config_path), "--check-config"])

        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "[OK] Configuration is valid." in captured.out
        assert "environment-secret" not in output
        assert "file-secret" not in output
        assert "file-user" not in output

    def test_invalid_config_is_actionable_and_redacted(self, monkeypatch, capsys):
        from src.cli import main

        password = "invalid-config-secret"  # pragma: allowlist secret
        monkeypatch.setenv(
            "LIBRUS_ACCOUNTS",
            json.dumps([{"username": "private-username", "password": password}]),
        )

        with pytest.raises(SystemExit) as exit_error:
            main(["--check-config"])

        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert exit_error.value.code == 2
        assert "[FAIL] Configuration is not ready." in captured.err
        assert "Next step:" in captured.err
        assert "private-username" not in output
        assert password not in output
        assert "Traceback" not in output


class TestDoctor:
    def test_config_path_can_follow_doctor_command(self, tmp_path, monkeypatch, capsys):
        from src.cli import main

        _set_accounts(monkeypatch, "environment-secret")
        config_path = tmp_path / "secrets.json"
        config_path.write_text(
            json.dumps(
                {
                    "accounts": [
                        {"alias": "from-file", "username": "file-user", "password": "file-secret"}
                    ],
                    "features": {"notifications": False, "attachments": False},
                }
            ),
            encoding="utf-8",
        )
        if os.name == "posix":
            config_path.chmod(0o600)

        main(["doctor", "--config", str(config_path)])

        captured = capsys.readouterr()
        assert "[OK] Configuration: 1 account configured." in captured.out
        assert "environment-secret" not in captured.out + captured.err

    def test_local_doctor_prepares_storage_without_network(self, tmp_path, monkeypatch, capsys):
        from src.cli import main

        _set_accounts(monkeypatch)
        state_dir = tmp_path / "state"
        download_dir = tmp_path / "downloads"
        monkeypatch.setenv("LIBRUS_STATE_DIR", str(state_dir))
        monkeypatch.setenv("LIBRUS_DOWNLOAD_DIR", str(download_dir))

        with (
            patch("src.librus_client.LibrusManager.check_account_connection") as live_check,
            patch("socket.socket.connect") as network_connect,
        ):
            main(["doctor"])

        captured = capsys.readouterr()
        assert "[OK] Configuration: 1 account configured." in captured.out
        assert "[OK] Notification storage is ready." in captured.out
        assert "[OK] Attachment storage is ready." in captured.out
        assert "[SKIP] Live Librus checks were not requested." in captured.out
        assert "doctor --live" in captured.out
        assert state_dir.is_dir()
        assert download_dir.is_dir()
        assert list(download_dir.iterdir()) == []
        if os.name == "posix":
            assert state_dir.stat().st_mode & 0o777 == 0o700
        live_check.assert_not_called()
        network_connect.assert_not_called()

    def test_live_doctor_checks_every_account_read_only(self, tmp_path, monkeypatch, capsys):
        from src.cli import main

        monkeypatch.setenv(
            "LIBRUS_ACCOUNTS",
            json.dumps(
                [
                    {"alias": "first", "username": "u1", "password": "p1"},
                    {"alias": "second", "username": "u2", "password": "p2"},
                ]
            ),
        )
        monkeypatch.setenv("LIBRUS_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setenv("LIBRUS_DOWNLOAD_DIR", str(tmp_path / "downloads"))
        fetch_profile = AsyncMock(return_value={"name": "not printed"})

        with patch("src.librus_client.LibrusManager.check_account_connection", fetch_profile):
            main(["doctor", "--live"])

        captured = capsys.readouterr()
        assert "contacts Librus and performs read-only checks" in captured.out
        assert "[OK] Librus account 'first': sign-in and read access work." in captured.out
        assert "[OK] Librus account 'second': sign-in and read access work." in captured.out
        assert "not printed" not in captured.out
        assert [call.args for call in fetch_profile.await_args_list] == [("first",), ("second",)]

    def test_live_failure_never_prints_raw_exception_or_credentials(
        self, tmp_path, monkeypatch, capsys
    ):
        from src.cli import main

        password = "live-doctor-secret"  # pragma: allowlist secret
        _set_accounts(monkeypatch, password)
        monkeypatch.setenv("LIBRUS_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setenv("LIBRUS_DOWNLOAD_DIR", str(tmp_path / "downloads"))
        fetch_profile = AsyncMock(side_effect=RuntimeError(password))

        with (
            patch("src.librus_client.LibrusManager.check_account_connection", fetch_profile),
            pytest.raises(SystemExit) as exit_error,
        ):
            main(["doctor", "--live"])

        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert exit_error.value.code == 1
        assert "[FAIL] Librus account 'test_student'" in captured.out
        assert "Check the credentials and internet connection" in captured.out
        assert password not in output
        assert "private-username" not in output
        assert "Traceback" not in output

    def test_storage_failure_is_redacted_and_actionable(self, tmp_path, monkeypatch, capsys):
        from src.cli import main

        marker = "storage-private-detail"
        _set_accounts(monkeypatch)
        monkeypatch.setenv("LIBRUS_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setenv("LIBRUS_DOWNLOAD_DIR", str(tmp_path / "downloads"))

        with (
            patch(
                "src.cli.verify_notification_state_storage",
                side_effect=PermissionError(marker),
            ),
            pytest.raises(SystemExit) as exit_error,
        ):
            main(["doctor"])

        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert exit_error.value.code == 1
        assert "[FAIL] Notification storage is not ready." in captured.out
        assert "Choose a state folder inside your user profile" in captured.out
        assert marker not in output
        assert "Traceback" not in output

    def test_attachment_check_never_deletes_preexisting_collision(self, tmp_path):
        from src.cli import _prepare_download_directory

        source_path = tmp_path / ".librus-mcp-doctor-fixed"
        source_descriptor = os.open(source_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        collision_path = source_path.with_name(f"{source_path.name}.link")
        collision_path.write_text("keep", encoding="utf-8")

        with (
            patch(
                "src.cli.tempfile.mkstemp",
                return_value=(source_descriptor, str(source_path)),
            ),
            pytest.raises(FileExistsError),
        ):
            _prepare_download_directory(tmp_path)

        assert collision_path.read_text(encoding="utf-8") == "keep"

    def test_attachment_check_attempts_temp_cleanup_after_link_cleanup_failure(self, tmp_path):
        from src.cli import _prepare_download_directory

        original_unlink = Path.unlink

        def fail_link_cleanup(path, *args, **kwargs):
            if path.name.endswith(".link"):
                raise OSError("link cleanup failed")
            return original_unlink(path, *args, **kwargs)

        with (
            patch.object(Path, "unlink", new=fail_link_cleanup),
            pytest.raises(OSError, match="link cleanup failed"),
        ):
            _prepare_download_directory(tmp_path)

        remaining = list(tmp_path.iterdir())
        assert len(remaining) == 1
        assert remaining[0].name.endswith(".link")
        original_unlink(remaining[0])
