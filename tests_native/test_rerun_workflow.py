"""The workflow that reruns jobs GitHub never started keeps a narrow scope."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
RERUN = WORKFLOWS / "rerun-unacquired.yml"
# Installed-artifact jobs run a copy of the tests without `.github/`.
pytestmark = pytest.mark.skipif(not RERUN.exists(), reason="source checkout only")
WATCHED = ["CI"]
NOT_ACQUIRED = "The job was not acquired by Runner of type hosted even after multiple attempts"
STUB = r"""#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
fixture = json.loads(open(os.environ["GH_FIXTURE"]).read())
if args[:2] == ["run", "rerun"]:
    with open(os.environ["GH_LOG"], "a") as log:
        log.write(" ".join(args) + "\n")
    sys.exit(0)
url = next(a for a in args if a.startswith("repos/"))
if "/check-runs/" in url:
    job = url.split("/check-runs/")[1].split("/")[0]
    if job in fixture["broken"]:
        sys.exit(1)
    data = fixture["annotations"].get(job, [])
else:
    data = {"total_count": len(fixture["jobs"]), "jobs": fixture["jobs"]}
query = args[args.index("--jq") + 1]
out = subprocess.run(["jq", "-r", query], input=json.dumps(data), text=True,
                     capture_output=True, check=True)
sys.stdout.write(out.stdout)
"""


def load(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    return loaded


def job(number: int, conclusion: str, *, ran: bool) -> dict[str, Any]:
    return {
        "id": number,
        "conclusion": conclusion,
        "runner_name": f"GitHub Actions {number}" if ran else "",
        "steps": [{"name": "Set up job"}] if ran else [],
    }


def test_the_watched_workflows_are_exactly_the_macos_ones() -> None:
    # Hosted macOS arm64 jobs are the ones GitHub left without a runner
    # (2026-11-23 and 2026-11-24). The weekly live check calls live Librus and
    # must never be rerun without the owner.
    watched = load(RERUN)["on"]["workflow_run"]["workflows"]
    assert watched == WATCHED
    macos = {
        load(path)["name"]
        for path in WORKFLOWS.glob("*.y*ml")
        if path != RERUN and "macos" in path.read_text()
    }
    assert macos and macos <= set(WATCHED)
    for path in WORKFLOWS.glob("*.y*ml"):
        if load(path)["name"] in watched:
            assert "live-check" not in path.read_text()


def test_it_can_only_rerun_and_only_a_failed_same_repository_run() -> None:
    workflow = load(RERUN)
    assert workflow["permissions"] == {}
    (job_,) = workflow["jobs"].values()
    assert job_["permissions"] == {"actions": "write", "checks": "read"}
    for condition in (
        "workflow_run.conclusion == 'failure'",
        "workflow_run.run_attempt < 3",
        "head_repository.full_name == github.repository",
    ):
        assert condition in job_["if"]
    (step,) = job_["steps"]
    assert "${{" not in step["run"]


LOST = [job(1, "success", ran=True), job(2, "cancelled", ran=False)]


@pytest.mark.skipif(
    sys.platform == "win32" or not (shutil.which("bash") and shutil.which("jq")),
    reason="needs bash and jq",
)
@pytest.mark.parametrize(
    ("jobs", "annotations", "broken", "reruns", "exit_code"),
    [
        pytest.param(LOST, {"2": NOT_ACQUIRED}, [], True, 0, id="lost-job"),
        pytest.param(
            [*LOST, job(3, "skipped", ran=False)],
            {"2": NOT_ACQUIRED},
            [],
            True,
            0,
            id="lost-job-and-skipped-dependent",
        ),
        pytest.param(
            [*LOST, job(3, "failure", ran=True)],
            {"2": NOT_ACQUIRED},
            [],
            False,
            0,
            id="lost-job-and-real-failure",
        ),
        pytest.param(LOST, {"2": "Fixture other notice"}, [], False, 0, id="no-notice"),
        pytest.param(
            # A job that ran can write any annotation itself, such as a test
            # printing `::error::`; only a job with no runner and no steps counts.
            [job(1, "failure", ran=True)],
            {"1": NOT_ACQUIRED},
            [],
            False,
            0,
            id="ran-job-quoting-the-notice",
        ),
        pytest.param([job(1, "success", ran=True)], {}, [], False, 0, id="passed"),
        pytest.param(LOST, {"2": NOT_ACQUIRED}, ["2"], False, 1, id="lookup-fails"),
    ],
)
def test_it_reruns_only_when_every_failed_job_never_got_a_runner(
    tmp_path: Path,
    jobs: list[dict[str, Any]],
    annotations: dict[str, str],
    broken: list[str],
    reruns: bool,
    exit_code: int,
) -> None:
    (step,) = next(iter(load(RERUN)["jobs"].values()))["steps"]
    stub = tmp_path / "bin" / "gh"
    stub.parent.mkdir()
    stub.write_text(STUB)
    stub.chmod(0o755)
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "jobs": jobs,
                "annotations": {
                    key: [{"annotation_level": "failure", "message": message}]
                    for key, message in annotations.items()
                },
                "broken": broken,
            }
        )
    )
    log = tmp_path / "gh.log"
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        env={
            **os.environ,
            "PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}",
            "GH_FIXTURE": str(fixture),
            "GH_LOG": str(log),
            "REPO": "fixture/repo",
            "RUN_ID": "41",
            "ATTEMPT": "1",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == exit_code, result.stderr
    calls = log.read_text().splitlines() if log.exists() else []
    assert calls == (["run rerun 41 --failed --repo fixture/repo"] if reruns else [])
