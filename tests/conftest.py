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
    yield
    LibrusManager._instances.clear()
    LibrusManager._tokens.clear()
    LibrusManager._config_cache = None
