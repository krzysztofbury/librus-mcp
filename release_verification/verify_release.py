#!/usr/bin/env python3
"""Verify that a release event, tag, checkout, and project version agree."""

import argparse
import re
import subprocess
import tomllib
from pathlib import Path

COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


class VerificationError(RuntimeError):
    """A release identity check failed."""


def read_project_version(project_file: Path) -> str:
    with project_file.open("rb") as file:
        project = tomllib.load(file).get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise VerificationError(f"project.version is missing from {project_file}")
    version = project["version"]
    if not version or version != version.strip():
        raise VerificationError("project.version must be a non-empty trimmed string")
    return version


def resolve_commit(repository: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--verify", revision],
        check=False,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip().lower()
    if result.returncode != 0 or COMMIT_PATTERN.fullmatch(commit) is None:
        detail = result.stderr.strip() or "revision did not resolve to a commit"
        raise VerificationError(f"cannot resolve {revision!r}: {detail}")
    return commit


def verify_release(repository: Path, tag: str, event_sha: str) -> str:
    version = read_project_version(repository / "pyproject.toml")
    expected_tag = f"v{version}"
    if tag != expected_tag:
        raise VerificationError(f"release tag {tag!r} does not match {expected_tag!r}")
    if COMMIT_PATTERN.fullmatch(event_sha.lower()) is None:
        raise VerificationError("release event SHA must be a full 40-character commit SHA")

    head_commit = resolve_commit(repository, "HEAD^{commit}")
    tag_commit = resolve_commit(repository, f"refs/tags/{tag}^{{commit}}")
    event_commit = event_sha.lower()
    if head_commit != tag_commit:
        raise VerificationError(
            f"checkout HEAD {head_commit} does not match tag commit {tag_commit}"
        )
    if head_commit != event_commit:
        raise VerificationError(
            f"checkout HEAD {head_commit} does not match release event SHA {event_commit}"
        )
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="release tag from the GitHub event")
    parser.add_argument("--event-sha", required=True, help="commit SHA from the GitHub event")
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    try:
        version = verify_release(repository, arguments.tag, arguments.event_sha)
    except VerificationError as error:
        raise SystemExit(f"release verification failed: {error}") from None
    print(f"verified release v{version}")


if __name__ == "__main__":
    main()
