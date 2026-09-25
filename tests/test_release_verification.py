"""Static and unit checks for the release verification path."""

import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from release_verification.verify_release import VerificationError, verify_release
from release_verification.verify_wheel import VerificationError as WheelVerificationError
from release_verification.verify_wheel import (
    parse_initialize_response,
    resolve_wheel,
)

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


def test_initialize_response_parser_accepts_one_json_rpc_response():
    response = parse_initialize_response(
        '{"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"librus-mcp"}}}\n'
    )

    assert response["result"]["serverInfo"]["name"] == "librus-mcp"


@pytest.mark.parametrize(
    ("stdout", "count"),
    [
        ("", 0),
        ('{"jsonrpc":"2.0","id":1,"result":{}}\n' * 2, 2),
    ],
)
def test_initialize_response_parser_rejects_missing_or_duplicate_response(stdout, count):
    with pytest.raises(
        WheelVerificationError, match=f"expected one initialize response, received {count}"
    ):
        parse_initialize_response(stdout)


def test_windows_runtime_timezone_data_is_declared():
    with (REPOSITORY / "pyproject.toml").open("rb") as file:
        dependencies = tomllib.load(file)["project"]["dependencies"]

    assert "tzdata>=2025.2; sys_platform == 'win32'" in dependencies


def test_wheel_resolver_accepts_directory_with_one_wheel(tmp_path):
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    wheel.touch()

    assert resolve_wheel(tmp_path) == wheel.resolve()


def test_wheel_resolver_accepts_direct_wheel_path(tmp_path):
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    wheel.touch()

    assert resolve_wheel(wheel) == wheel.resolve()


@pytest.mark.parametrize("wheel_count", [0, 2])
def test_wheel_resolver_requires_exactly_one_wheel_in_directory(tmp_path, wheel_count):
    for index in range(wheel_count):
        (tmp_path / f"example-{index}.whl").touch()

    with pytest.raises(WheelVerificationError, match="exactly one wheel"):
        resolve_wheel(tmp_path)


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


def test_ci_verifies_installed_wheel_on_supported_operating_systems():
    workflow = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    compatibility_job = workflow.split("  compatibility:\n", maxsplit=1)[1]

    assert "runs-on: ${{ matrix.os }}" in compatibility_job
    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in compatibility_job
    assert "uv run python release_verification/verify_wheel.py dist" in compatibility_job
    assert "checksum:" not in compatibility_job
    assert "permissions:\n  contents: read" in workflow
    assert workflow.count("persist-credentials: false") == 2


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
    publish_steps = publish_job.split("    steps:\n", maxsplit=1)[1]

    assert "id-token: write" not in verify_job
    assert "uses: actions/upload-artifact@" in verify_job
    assert "needs: verify" in publish_job
    assert "id-token: write" in publish_job
    # Only artifact download, checksum verification, and publication may run
    # in the job that can request a PyPI publishing token.
    assert [line.strip() for line in publish_steps.splitlines() if line.startswith("      - ")] == [
        "- name: Download verified distributions",
        "- name: Verify distribution checksums",
        "- name: Publish to PyPI",
    ]
    assert publish_steps.count("        run: ") == 1
    assert "uses: actions/download-artifact@" in publish_job
    assert "artifact-ids: ${{ needs.verify.outputs.artifact-id }}" in publish_job
    checksum_step = publish_steps.split("      - name: Verify distribution checksums\n", 1)[1]
    checksum_step = checksum_step.split("      - name: Publish to PyPI\n", 1)[0]
    checksum_commands = [
        line.strip() for line in checksum_step.split("        run: |\n", 1)[1].strip().splitlines()
    ]
    assert checksum_commands == [
        'test -n "$EXPECTED_MANIFEST_SHA256"',
        'echo "$EXPECTED_MANIFEST_SHA256  dist/SHA256SUMS" | sha256sum --check --strict',
        "sha256sum --check --strict dist/SHA256SUMS",
        "mkdir verified-dist",
        "while read -r _ distribution; do",
        'cp -- "$distribution" verified-dist/',
        "done < dist/SHA256SUMS",
    ]
    assert "uses: pypa/gh-action-pypi-publish@" in publish_job
    assert "packages-dir: verified-dist/" in publish_job
    assert "attestations: true" in publish_job
