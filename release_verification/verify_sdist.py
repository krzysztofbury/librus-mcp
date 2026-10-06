#!/usr/bin/env python3
"""Audit the native source distribution and rebuild its wheel without checkout source."""

import argparse
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

from release_verification.verify_wheel import VerificationError, read_project_version


def verify_sdist(repository: Path, archive: Path, output: Path) -> None:
    if archive.is_dir():
        archives = list(archive.glob("*.tar.gz"))
        if len(archives) != 1:
            raise VerificationError("expected exactly one source distribution")
        archive = archives[0]
    version = read_project_version(repository / "pyproject.toml")
    prefix = f"librus_mcp-{version}"
    with tarfile.open(archive) as source:
        files: dict[str, bytes] = {}
        for member in source.getmembers():
            name = PurePosixPath(member.name)
            if name.parts[0] != prefix or name.is_absolute() or ".." in name.parts:
                raise VerificationError("source distribution contains an unsafe path")
            relative = PurePosixPath(*name.parts[1:])
            if member.isdir():
                continue
            if not member.isfile() or member.size > 512 * 1024:
                raise VerificationError("source distribution contains an unsafe member")
            if "legacy_reference" in relative.parts or relative.parts[0] in {"tests", "mutation"}:
                raise VerificationError("source distribution contains historical material")
            if relative.parts[0] == "src" and relative.parts[1] != "librus_mcp":
                raise VerificationError("source distribution contains the old source namespace")
            file = source.extractfile(member)
            if file is None:
                raise VerificationError("source distribution member is unreadable")
            with file:
                body = file.read()
            files[str(relative)] = body
            original = repository / relative
            if original.is_file() and original.read_bytes() != body:
                raise VerificationError("source distribution differs from the reviewed source")
        required = {"LICENSE", "LICENSE_REVIEW.md", "src/librus_mcp/cli.py", "tests_native/wire.py"}
        # Git can check text out with CRLF on Windows. Keep the exact header
        # requirement while accepting either platform's newline bytes.
        if not required <= files.keys() or not files["LICENSE"].startswith(
            (b"MIT License\n", b"MIT License\r\n")
        ):
            raise VerificationError("source distribution is missing native license/source proof")
        if b"License-Expression: MIT" not in files.get("PKG-INFO", b""):
            raise VerificationError("source distribution license metadata is not MIT")
    output.mkdir(parents=True, exist_ok=True)
    if list(output.iterdir()):
        raise VerificationError("rebuilt-wheel destination must be empty")
    subprocess.run(
        [
            "uv",
            "build",
            str(archive.resolve()),
            "--wheel",
            "--no-build-isolation",
            "--out-dir",
            str(output.resolve()),
        ],
        check=True,
    )
    print("Native MIT source inventory and wheel-from-sdist build passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    arguments = parser.parse_args()
    verify_sdist(Path(__file__).resolve().parents[1], arguments.sdist, arguments.out_dir)


if __name__ == "__main__":
    main()
