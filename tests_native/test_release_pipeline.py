"""Who can publish, and which commit a release may publish from."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/publish.yml"
RELEASE_FILES = ("pyproject.toml", "server.json", "README.md", "Dockerfile")


@pytest.fixture
def jobs():
    # The installed-wheel run has neither the workflow nor a YAML parser.
    yaml = pytest.importorskip("yaml")
    if not WORKFLOW.exists():
        pytest.skip("source checkout only")
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"release"}
    assert workflow["on"]["release"]["types"] == ["published"]
    assert workflow["permissions"] == {"contents": "read"}
    return workflow["jobs"]


def script(job):
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_only_the_gated_jobs_can_publish_or_write_to_the_release(jobs):
    assert jobs["publish"]["environment"]["name"] == "pypi"
    assert set(jobs["image"]["needs"]) == {"verify", "publish"}
    assert set(jobs["registry"]["needs"]) == {"verify", "publish", "image"}
    writers = {name for name, job in jobs.items() if "permissions" in job}
    assert {name for name in writers if jobs[name]["permissions"].get("id-token") == "write"} == {
        "publish",
        "registry",
    }
    assert {name for name in writers if jobs[name]["permissions"].get("contents") == "write"} == {
        "registry"
    }


def test_release_values_reach_shell_only_through_the_environment(jobs):
    for job in jobs.values():
        assert "${{" not in script(job)
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] == "false"


def test_every_published_file_is_checked_first(jobs):
    assert "verify_release.py" in script(jobs["verify"])
    for name in ("publish", "image", "registry"):
        assert "sha256sum --check --strict SHA256SUMS" in script(jobs[name])


def git(directory, *args):
    subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@invalid", *args],
        cwd=directory,
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize("merged", [True, False])
def test_a_release_must_be_on_main(tmp_path, monkeypatch, merged):
    if not WORKFLOW.exists():
        pytest.skip("source checkout only")
    monkeypatch.syspath_prepend(ROOT / "release_verification")
    from verify_release import (
        VerificationError,
        read_project_version,
        resolve_commit,
        verify_release,
    )

    origin, checkout = tmp_path / "origin.git", tmp_path / "checkout"
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    git(tmp_path, "clone", str(origin), str(checkout))
    for name in RELEASE_FILES:
        shutil.copy(ROOT / name, checkout)
    git(checkout, "switch", "-c", "main")
    git(checkout, "add", ".")
    git(checkout, "commit", "-m", "Candidate")
    git(checkout, "push", "origin", "main")
    if not merged:
        git(checkout, "switch", "-c", "unmerged")
        git(checkout, "commit", "--allow-empty", "-m", "Unmerged")
        # Resolves before the remote branch if the check uses the short name.
        git(checkout, "tag", "origin/main")
    version = read_project_version(checkout / "pyproject.toml")
    git(checkout, "tag", f"v{version}")
    head = resolve_commit(checkout, "HEAD^{commit}")
    if merged:
        assert verify_release(checkout, f"v{version}", head) == version
    else:
        with pytest.raises(VerificationError, match="not on main"):
            verify_release(checkout, f"v{version}", head)
