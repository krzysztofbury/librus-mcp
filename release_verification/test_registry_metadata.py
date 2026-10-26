"""The MCP Registry listing stays in step with the package it publishes."""

import json
import shutil
from pathlib import Path

import pytest

from release_verification.verify_release import (
    VerificationError,
    read_project_version,
    verify_registry_metadata,
)

ROOT = Path(__file__).resolve().parents[1]


def copy_project(tmp_path: Path) -> Path:
    for name in ("pyproject.toml", "server.json", "README.md"):
        shutil.copy(ROOT / name, tmp_path / name)
    return tmp_path


def test_registry_metadata_matches_the_project():
    verify_registry_metadata(ROOT, read_project_version(ROOT / "pyproject.toml"))


@pytest.mark.parametrize("drift", ["version", "package", "marker"])
def test_registry_metadata_drift_blocks_the_release(drift, tmp_path):
    project = copy_project(tmp_path)
    version = read_project_version(project / "pyproject.toml")
    server = json.loads((project / "server.json").read_text())
    if drift == "version":
        server["version"] = "0.0.0"
    elif drift == "package":
        server["packages"][0]["version"] = "0.0.0"
    else:
        server["name"] = "io.github.example/other"
    (project / "server.json").write_text(json.dumps(server))
    with pytest.raises(VerificationError):
        verify_registry_metadata(project, version)
