"""Test isolation and mutmut's per-test hit collection across the stdio boundary."""

import json

import pytest

from tests_native.mutation_support import mutation_is_collecting


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path_factory):
    # Default features provision ~/.librus-mcp. Tests and their child servers
    # inherit this disposable home, never the developer's real state.
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


@pytest.fixture(autouse=True)
def mutation_child_reports(request, monkeypatch, tmp_path_factory):
    if mutation_is_collecting():
        directory = tmp_path_factory.mktemp("mutation-stdio-hits")
        request.node.stash[MUTATION_REPORTS] = directory
        monkeypatch.setenv("NATIVE_MUTATION_REPORT_DIR", str(directory))


MUTATION_REPORTS = pytest.StashKey()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown(item):
    if MUTATION_REPORTS not in item.stash:
        return
    import mutmut

    reports = list(item.stash[MUTATION_REPORTS].glob("*.json"))
    if not reports:
        raise RuntimeError("mutation statistics did not cross the MCP subprocess boundary")
    for report in reports:
        mutmut._stats.update(json.loads(report.read_text(encoding="utf-8")))
