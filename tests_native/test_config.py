"""Configuration security and precedence at the new CLI/config boundary."""

import asyncio
import json
import os
from pathlib import Path

import pytest
from librus_python_api.files import prepare_attachment_directory

from librus_mcp.cli import main
from librus_mcp.config import ConfigError, load_config


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    for name in os.environ:
        if name.startswith("LIBRUS_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def config_data():
    return {
        "accounts": [
            {
                "alias": "fixture",
                "username": "fixture-login",
                "password": "fixture-only",  # pragma: allowlist secret - fixture only
            }
        ],
        # Public deterministic test value, never a deployment key.
        "context_key": bytes(range(32)).hex(),
    }


def write_config(path: Path, data=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config_data() if data is None else data))
    path.chmod(0o600)
    if os.name == "nt":
        set_windows_acl(path)


def set_windows_acl(path, *, shared=False):
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    acl = win32security.ACL()
    acl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.GENERIC_ALL, user)
    if shared:
        acl.AddAccessAllowedAce(
            win32security.ACL_REVISION,
            win32con.GENERIC_READ,
            win32security.CreateWellKnownSid(win32security.WinWorldSid),
        )
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        acl,
        None,
    )


def test_xdg_selection_ignores_cwd_and_explicit_cli_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("secrets.json").write_text('{"not": "configuration"}')
    xdg = tmp_path / "xdg" / "librus-mcp" / "config.json"
    write_config(xdg)
    assert load_config().accounts[0].alias == "fixture"
    monkeypatch.setenv("LIBRUS_ACCOUNTS", "not-json")
    monkeypatch.setenv("LIBRUS_CONFIG", "nonexistent")
    assert load_config(xdg).accounts[0].alias == "fixture"
    with pytest.raises(ConfigError, match="not both"):
        load_config()


@pytest.mark.parametrize(
    "change",
    [
        {"context_key": "not-a-key"},
        {"accounts": []},
        {"features": {"notifications": "true"}},
        {"features": {"unknown": True}},
        {"state_dir": "relative/path"},
        {"extra": "not-supported"},
        {
            "accounts": [
                {
                    "alias": " bad ",
                    "username": "private-login",
                    "password": "private",  # pragma: allowlist secret - redaction fixture
                }
            ]
        },
        {
            "accounts": [
                {
                    "alias": "fixture",
                    "username": "",
                    "password": "private",  # pragma: allowlist secret - validation fixture
                }
            ]
        },
    ],
)
def test_bad_config_is_rejected_without_raw_inputs(change, tmp_path, capsys):
    path = tmp_path / "config.json"
    write_config(path, config_data() | change)
    with pytest.raises(SystemExit) as error:
        main(["--config", str(path), "--check-config"])
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid configuration" in captured.err
    assert "private-login" not in captured.err and "not-a-key" not in captured.err
    assert "Traceback" not in captured.err


def test_duplicate_alias_fails_closed_and_loading_never_creates_a_key(tmp_path):
    path = tmp_path / "config.json"
    data = config_data()
    data["accounts"] *= 2
    write_config(path, data)
    with pytest.raises(ConfigError):
        load_config(path)
    data = config_data() | {"state_dir": str(tmp_path / "state")}
    del data["context_key"]
    write_config(path, data)
    assert load_config(path).context_key is None
    assert list(tmp_path.iterdir()) == [path]


def test_missing_context_key_is_created_once_and_reused(tmp_path, capsys):
    from librus_mcp.context_key import KEY_FILENAME, provision_context_key

    path = tmp_path / "config.json"
    state = tmp_path / "fresh" / "state"
    data = config_data() | {"state_dir": str(state)}
    del data["context_key"]
    write_config(path, data)

    async def concurrent_first_starts():
        config = load_config(path)
        return await asyncio.gather(*(provision_context_key(config) for _ in range(4)))

    keys = {config.key_bytes() for config in asyncio.run(concurrent_first_starts())}
    assert len(keys) == 1
    assert "context key" in capsys.readouterr().err
    assert load_config(path).key_bytes() in keys
    assert sorted(item.name for item in state.iterdir()) == [KEY_FILENAME]
    if os.name == "posix":
        assert (state / KEY_FILENAME).stat().st_mode & 0o777 == 0o600
        assert state.stat().st_mode & 0o777 == 0o700
    # An explicit key always wins over the stored one.
    write_config(path, data | {"context_key": bytes(range(32)).hex()})
    assert load_config(path).key_bytes() == bytes(range(32))


def test_invalid_stored_context_key_is_never_replaced(tmp_path):
    from librus_mcp.context_key import KEY_FILENAME

    state = tmp_path / "state"
    asyncio.run(prepare_attachment_directory(state))
    write_config(state / KEY_FILENAME, {"context_key": "damaged"})
    path = tmp_path / "config.json"
    data = config_data() | {"state_dir": str(state)}
    del data["context_key"]
    write_config(path, data)
    with pytest.raises(ConfigError, match="restore it from backup"):
        load_config(path)
    assert json.loads((state / KEY_FILENAME).read_text()) == {"context_key": "damaged"}


def test_behaviour_notes_from_1x_are_ignored_with_a_notice(tmp_path, capsys):
    from librus_mcp.server import create_server

    path = tmp_path / "config.json"
    write_config(path, config_data() | {"features": {"behaviour_notes": True}})
    config = load_config(path)
    assert "behaviour notes are unavailable" in capsys.readouterr().err
    names = {tool.name for tool in asyncio.run(create_server(config).list_tools())}
    assert not any("behaviour" in name for name in names)


def test_environment_secrets_are_hidden_and_overrides_validated(monkeypatch):
    data = config_data()
    monkeypatch.setenv("LIBRUS_ACCOUNTS", json.dumps(data["accounts"]))
    monkeypatch.setenv("LIBRUS_CONTEXT_KEY", data["context_key"])
    config = load_config()
    assert config.key_bytes() == bytes(range(32))
    assert config.accounts[0].messaging_backend.value == "modern"
    rendered = repr(config)
    assert "fixture-login" not in rendered and "fixture-only" not in rendered
    assert data["context_key"] not in rendered
    monkeypatch.setenv("LIBRUS_FEATURES", "null")
    with pytest.raises(ConfigError):
        load_config()


def test_deeply_nested_json_is_a_redacted_configuration_error(monkeypatch):
    monkeypatch.setenv("LIBRUS_ACCOUNTS", "[" * 2000 + "]" * 2000)
    with pytest.raises(ConfigError, match="invalid"):
        load_config()


def test_configuration_rejects_large_files_and_symlinks(tmp_path):
    path = tmp_path / "config.json"
    write_config(path)
    symlink = tmp_path / "link.json"
    try:
        symlink.symlink_to(path)
    except OSError:
        pytest.skip("symlink creation is not permitted on this host")
    with pytest.raises(ConfigError, match="symlink|regular|reparse"):
        load_config(symlink)
    path.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(ConfigError, match="size limit"):
        load_config(path)


@pytest.mark.skipif(os.name != "posix", reason="POSIX credential mode boundary")
def test_shared_own_credential_file_is_restricted_and_special_files_rejected(tmp_path):
    path = tmp_path / "config.json"
    write_config(path)
    path.chmod(0o644)
    # The user's own file is restricted in place instead of refusing to start.
    assert load_config(path).accounts[0].alias == "fixture"
    assert path.stat().st_mode & 0o777 == 0o600
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(ConfigError, match="regular file"):
        load_config(fifo)


@pytest.mark.skipif(os.name != "nt", reason="actual Windows credential ACL boundary")
def test_windows_config_rejects_shared_acl_and_hardlink_without_modifying_file(tmp_path):
    path = tmp_path / "config.json"
    write_config(path)
    assert load_config(path).accounts[0].alias == "fixture"
    original = path.read_bytes()
    set_windows_acl(path, shared=True)
    with pytest.raises(ConfigError, match="owner-private Windows ACL"):
        load_config(path)
    assert path.read_bytes() == original
    set_windows_acl(path)
    link = tmp_path / "hardlink.json"
    os.link(path, link)
    with pytest.raises(ConfigError, match="regular"):
        load_config(path)
    assert path.read_bytes() == original


def test_key_generation_is_explicit_and_does_not_touch_storage(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["--generate-context-key"])
    output = capsys.readouterr()
    assert len(bytes.fromhex(output.out.strip())) == 32
    assert output.err == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("feature", ["send_message", "attachments", "notifications"])
def test_explicit_optional_feature_validates_without_provisioning(feature, tmp_path, capsys):
    path = tmp_path / "config.json"
    state = tmp_path / "state"
    write_config(
        path,
        config_data()
        | {"features": {feature: True}, "state_dir": str(state), "download_dir": str(state)},
    )
    main(["--config", str(path), "--check-config"])
    assert "[OK]" in capsys.readouterr().out
    assert not state.exists()


def test_doctor_is_offline_and_explicit_storage_probe_leaves_existing_state_untouched(
    tmp_path, capsys
):
    path = tmp_path / "config.json"
    state = tmp_path / "state"
    write_config(path, config_data() | {"state_dir": str(state)})
    main(["--config", str(path), "--doctor"])
    report = json.loads(capsys.readouterr().out)
    assert report["network"] == "not_attempted" and not report["storage_checked"]
    assert not state.exists()
    asyncio.run(prepare_attachment_directory(state))
    existing = state / "fixture.notifications.json"
    existing.write_bytes(b"Original old state")
    main(["--config", str(path), "--doctor", "--doctor-storage"])
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok" and report["storage_checked"]
    assert list(state.iterdir()) == [existing]
    assert existing.read_bytes() == b"Original old state"


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory mode boundary")
def test_enabled_features_create_missing_private_ancestors_on_a_fresh_host(tmp_path):
    from librus_mcp.config import AppConfig
    from librus_mcp.runtime import prepare_directories

    home = tmp_path / "home"
    home.mkdir(mode=0o755)
    config = AppConfig.model_validate(
        config_data()
        | {
            "features": {"notifications": True, "attachments": True},
            "state_dir": str(home / ".librus-mcp" / "state"),
            "download_dir": str(home / ".librus-mcp" / "downloads"),
        }
    )
    asyncio.run(prepare_directories(config))
    for directory in (
        home / ".librus-mcp",
        home / ".librus-mcp" / "state",
        home / ".librus-mcp" / "downloads" / "native-v2",
    ):
        assert directory.stat().st_mode & 0o777 == 0o700
    # Existing ancestors are used as found, never chmodded.
    assert home.stat().st_mode & 0o777 == 0o755


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory mode boundary")
def test_own_shared_1x_directory_is_restricted_instead_of_failing(tmp_path, capsys):
    from librus_mcp.config import AppConfig
    from librus_mcp.runtime import prepare_directories

    downloads = tmp_path / "downloads"
    downloads.mkdir(mode=0o755)
    (downloads / "old.pdf").write_bytes(b"kept")
    config = AppConfig.model_validate(
        config_data() | {"features": {"attachments": True}, "download_dir": str(downloads)}
    )
    asyncio.run(prepare_directories(config))
    assert downloads.stat().st_mode & 0o777 == 0o700
    assert (downloads / "old.pdf").read_bytes() == b"kept"
    assert "owner-only" in capsys.readouterr().err


def test_unusable_directory_fails_startup_with_one_line(tmp_path, capsys):
    downloads = tmp_path / "downloads"
    downloads.write_bytes(b"not a directory")
    path = tmp_path / "config.json"
    write_config(
        path,
        config_data() | {"features": {"attachments": True}, "download_dir": str(downloads)},
    )
    with pytest.raises(SystemExit) as stopped:
        main(["--config", str(path)])
    assert stopped.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.count("\n") == 1 and "(STORAGE)" in output.err
    assert "fixture" not in output.err
    assert downloads.read_bytes() == b"not a directory"
