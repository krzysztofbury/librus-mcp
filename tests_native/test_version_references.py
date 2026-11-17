"""Documentation and operator notices must not name a release that is no longer current."""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "pyproject.toml"
MIGRATION = ROOT / "MIGRATION_2_0.md"
SPEC = ROOT / "SPEC.md"


@pytest.fixture
def project_version():
    # The installed-wheel run has no source checkout.
    if not (PROJECT.exists() and MIGRATION.exists() and SPEC.exists()):
        pytest.skip("source checkout only")
    return tomllib.loads(PROJECT.read_text(encoding="utf-8"))["project"]["version"]


def test_the_upgrade_guide_pins_only_the_current_release(project_version):
    pins = re.findall(r"librus-mcp==([0-9][^\s`'\"]*)", MIGRATION.read_text(encoding="utf-8"))
    assert pins, "the upgrade section must tell the reader which release to pin"
    assert set(pins) == {project_version}


def test_the_upgrade_guide_does_not_say_the_readme_targets_an_old_release(project_version):
    text = MIGRATION.read_text(encoding="utf-8")
    assert not re.search(r"README\]\(README\.md\) targets \d", text)
    assert "current 2.1 catalog" not in text


def test_the_spec_title_names_no_release(project_version):
    title = SPEC.read_text(encoding="utf-8").splitlines()[0]
    assert not re.search(r"\d+\.\d+", title), title
