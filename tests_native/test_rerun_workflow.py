"""The workflow that reruns jobs GitHub never started keeps a narrow scope."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
RERUN = WORKFLOWS / "rerun-unacquired.yml"


def load(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    return loaded


def test_every_workflow_with_a_macos_job_is_watched() -> None:
    # Hosted macOS arm64 jobs are the ones GitHub left without a runner
    # (2026-11-23 and 2026-11-24); a new macOS workflow must be listed too.
    watched = set(load(RERUN)["on"]["workflow_run"]["workflows"])
    macos = {
        load(path)["name"]
        for path in WORKFLOWS.glob("*.y*ml")
        if path != RERUN and "macos" in path.read_text()
    }
    assert macos and macos <= watched


def test_it_can_only_rerun_and_only_a_failed_same_repository_run() -> None:
    workflow = load(RERUN)
    assert workflow["permissions"] == {}
    (job,) = workflow["jobs"].values()
    assert job["permissions"] == {"actions": "write", "checks": "read"}
    for condition in (
        "workflow_run.conclusion == 'failure'",
        "workflow_run.run_attempt < 3",
        "head_repository.full_name == github.repository",
    ):
        assert condition in job["if"]
    (step,) = job["steps"]
    # Event fields reach the script through the environment, never inline.
    assert "${{" not in step["run"]
    assert step["run"].count("gh run rerun") == 1
