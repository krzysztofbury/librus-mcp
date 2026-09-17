"""Static and unit checks for the release verification path."""

import re
import subprocess
from pathlib import Path

import pytest

from release_verification.verify_release import VerificationError, verify_release
from release_verification.verify_wheel import parse_initialize_response

REPOSITORY = Path(__file__).resolve().parents[1]
WORKFLOWS = REPOSITORY / ".github" / "workflows"
ACTION_REFERENCE = re.compile(r"^\s*-?\s*uses:\s*\S+@([0-9a-f]{40})\s+#\s+\S+\s*$")


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def release_repository(tmp_path: Path) -> tuple[Path, str]:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "1.2.4"\n', encoding="utf-8"
    )
    run_git(tmp_path, "init", "--quiet")
    run_git(tmp_path, "add", "pyproject.toml")
    run_git(
        tmp_path,
        "-c",
        "user.name=Release Test",
        "-c",
        "user.email=release@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "release",
    )
    run_git(tmp_path, "tag", "v1.2.4")
    return tmp_path, run_git(tmp_path, "rev-parse", "HEAD")


def test_release_identity_accepts_matching_tag_and_commits(tmp_path):
    repository, commit = release_repository(tmp_path)

    assert verify_release(repository, "v1.2.4", commit) == "1.2.4"


@pytest.mark.parametrize("tag", ["1.2.4", "v1.2.3"])
def test_release_identity_rejects_wrong_tag(tmp_path, tag):
    repository, commit = release_repository(tmp_path)

    with pytest.raises(VerificationError, match="does not match"):
        verify_release(repository, tag, commit)


def test_release_identity_rejects_event_commit_mismatch(tmp_path):
    repository, _ = release_repository(tmp_path)

    with pytest.raises(VerificationError, match="event SHA"):
        verify_release(repository, "v1.2.4", "0" * 40)


def test_release_identity_rejects_checkout_after_tag(tmp_path):
    repository, _ = release_repository(tmp_path)
    (repository / "post-tag-change").write_text("new commit\n", encoding="utf-8")
    run_git(repository, "add", "post-tag-change")
    run_git(
        repository,
        "-c",
        "user.name=Release Test",
        "-c",
        "user.email=release@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "post-tag change",
    )
    head_commit = run_git(repository, "rev-parse", "HEAD")

    with pytest.raises(VerificationError, match="does not match tag commit"):
        verify_release(repository, "v1.2.4", head_commit)


def test_initialize_response_parser_requires_one_json_rpc_response():
    response = parse_initialize_response(
        '{"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"librus-mcp"}}}\n'
    )

    assert response["result"]["serverInfo"]["name"] == "librus-mcp"


def test_all_third_party_actions_are_pinned_with_readable_comments():
    action_lines = [
        line
        for pattern in ("*.yml", "*.yaml")
        for workflow in WORKFLOWS.glob(pattern)
        for line in workflow.read_text(encoding="utf-8").splitlines()
        if "uses:" in line
    ]

    assert action_lines
    assert all(ACTION_REFERENCE.fullmatch(line) for line in action_lines)


def test_publish_workflow_keeps_all_verification_before_publish():
    workflow = (WORKFLOWS / "publish.yml").read_text(encoding="utf-8")
    publish_index = workflow.index("- name: Publish to PyPI")
    required_steps = [
        "- name: Verify release identity",
        "- name: Check lockfile is up to date",
        "uv sync --locked --python 3.14",
        "- name: Ruff check",
        "- name: Ruff format check",
        "- name: Bandit security check",
        "- name: Run tests",
        "- name: Build package",
        "- name: Verify built wheel",
    ]

    assert "ref: ${{ github.event.release.tag_name }}" in workflow
    assert "fetch-depth: 0" in workflow
    assert all(workflow.index(step) < publish_index for step in required_steps)


def test_publish_credentials_are_isolated_from_build_and_test_code():
    workflow = (WORKFLOWS / "publish.yml").read_text(encoding="utf-8")
    verify_job, publish_job = workflow.split("  publish:\n", maxsplit=1)

    assert "id-token: write" not in verify_job
    assert "uses: actions/upload-artifact@" in verify_job
    assert "needs: verify" in publish_job
    assert "id-token: write" in publish_job
    assert "uses: actions/download-artifact@" in publish_job
    assert "artifact-ids: ${{ needs.verify.outputs.artifact-id }}" in publish_job
    assert "EXPECTED_MANIFEST_SHA256" in publish_job
    assert 'echo "$EXPECTED_MANIFEST_SHA256  dist/SHA256SUMS"' in publish_job
    assert "sha256sum --check --strict dist/SHA256SUMS" in publish_job
    assert 'cp -- "$distribution" verified-dist/' in publish_job
    assert "uses: pypa/gh-action-pypi-publish@" in publish_job
    assert "packages-dir: verified-dist/" in publish_job
    assert "attestations: true" in publish_job
    assert "uv run" not in publish_job
