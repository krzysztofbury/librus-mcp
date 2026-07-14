import os
import pytest


@pytest.fixture(autouse=True, scope="session")
def set_test_credentials():
    """Provide a minimal LIBRUS_ACCOUNTS so config.load_config() works in tests."""
    original = os.environ.get("LIBRUS_ACCOUNTS")
    os.environ["LIBRUS_ACCOUNTS"] = (  # pragma: allowlist secret
        '[{"alias":"test_student","username":"00000","password":"fake"}]'
    )
    yield
    if original is None:
        del os.environ["LIBRUS_ACCOUNTS"]
    else:
        os.environ["LIBRUS_ACCOUNTS"] = original


@pytest.fixture(autouse=True)
def reset_librus_manager():
    """Clear LibrusManager caches between tests."""
    from src.librus_client import LibrusManager

    LibrusManager._instances.clear()
    LibrusManager._tokens.clear()
    LibrusManager._config_cache = None
    LibrusManager._notification_locks.clear()
    LibrusManager._client_locks.clear()
    LibrusManager._auth_cooldowns.clear()
    LibrusManager._timed_out_workers.clear()
    yield
    LibrusManager._instances.clear()
    LibrusManager._tokens.clear()
    LibrusManager._config_cache = None
    LibrusManager._notification_locks.clear()
    LibrusManager._client_locks.clear()
    LibrusManager._auth_cooldowns.clear()
    LibrusManager._timed_out_workers.clear()


@pytest.fixture(autouse=True)
def reset_pending_confirmations():
    """Clear send_message confirmation tokens between tests."""
    from src import server

    server._pending_confirmations.clear()
    yield
    server._pending_confirmations.clear()


@pytest.fixture(autouse=True)
def reset_optional_tools():
    """Unregister optional tools between tests so each test sees a clean
    FastMCP registry and gating tests prove the real registration path."""
    from src import server

    def _clear():
        for name in list(server._registered_optional_tools):
            server.mcp._tool_manager._tools.pop(name, None)
        server._registered_optional_tools.clear()

    _clear()
    yield
    _clear()
