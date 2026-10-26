#!/usr/bin/env python3
"""Verify that a release event, tag, checkout, and project version agree."""

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path

COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


class VerificationError(RuntimeError):
    """A release verification check failed."""


def read_project_version(project_file: Path) -> str:
    with project_file.open("rb") as file:
        project = tomllib.load(file).get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise VerificationError(f"project.version is missing from {project_file}")
    version = project["version"]
    if not version or version != version.strip():
        raise VerificationError("project.version must be a non-empty trimmed string")
    return version


def verify_registry_metadata(repository: Path, version: str) -> None:
    """server.json and the README ownership marker must describe this release."""
    with (repository / "pyproject.toml").open("rb") as file:
        name = tomllib.load(file)["project"]["name"]
    server = json.loads((repository / "server.json").read_text(encoding="utf-8"))
    if server.get("version") != version:
        raise VerificationError(f"server.json version must be {version!r}")
    packages = [p for p in server.get("packages", []) if p.get("registryType") == "pypi"]
    if [(p.get("identifier"), p.get("version")) for p in packages] != [(name, version)]:
        raise VerificationError(f"server.json must list PyPI package {name} {version}")
    # The registry proves PyPI ownership from this marker in the published README.
    marker = f"<!-- mcp-name: {server.get('name')} -->"
    if marker not in (repository / "README.md").read_text(encoding="utf-8"):
        raise VerificationError(f"README.md must contain {marker}")


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
    verify_registry_metadata(repository, version)
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
