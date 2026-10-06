#!/usr/bin/env python3
"""Run a bounded, disposable native MCP safety campaign with mutmut 3."""

import argparse
import fnmatch
import hashlib
import importlib.metadata
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

TARGETS = (
    "librus_mcp.presentation.x_validate_window_cursor*",
    "librus_mcp.presentation.x_window_page*",
    "librus_mcp.message_tools.x_require_binding*",
)


@contextmanager
def scratch_directory():
    if root := os.environ.get("AGENT_SCRATCH_DIR"):
        # The shell wrapper owns the entire group and waits before cleanup.
        # Do not detach descendants or delete their files during signal unwind.
        yield Path(tempfile.mkdtemp(prefix="librus-native-mutations-", dir=root))
    else:
        with tempfile.TemporaryDirectory(prefix="librus-native-mutations-") as temporary:
            yield Path(temporary)


def command(arguments, *, directory, environment, capture=False):
    # A failed/interrupted runner can leave pytest and stdio children alive.
    # Stop its process group before TemporaryDirectory removes their files.
    wrapper_owned = "AGENT_SCRATCH_DIR" in environment
    with subprocess.Popen(
        arguments,
        cwd=directory,
        env=environment,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        start_new_session=not wrapper_owned,
    ) as process:
        try:
            stdout, stderr = process.communicate()
        finally:
            if wrapper_owned:
                if process.poll() is None:
                    process.terminate()
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if wrapper_owned:
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            if not wrapper_owned:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if process.returncode:
            raise subprocess.CalledProcessError(
                process.returncode, arguments, output=stdout, stderr=stderr
            )
        return stdout


def run(report: Path | None, baseline: Path | None) -> None:
    if os.name != "posix":
        raise SystemExit(
            "mutmut's fork-based campaign requires POSIX; ordinary Windows CI is unchanged"
        )
    if importlib.metadata.version("mutmut") != "3.7.0":
        raise SystemExit("install the locked mutation group with mutmut 3.7.0")
    repository = Path(__file__).resolve().parents[1]
    with scratch_directory() as directory:
        for name in ("src/librus_mcp", "tests_native"):
            shutil.copytree(
                repository / name, directory / name, ignore=shutil.ignore_patterns("__pycache__")
            )
        for name in ("pyproject.toml", "uv.lock"):
            shutil.copy2(repository / name, directory / name)
        environment = os.environ.copy()
        for name in list(environment):
            if name.startswith("LIBRUS_") or name in {
                "PYTHONPATH",
                "MUTANT_UNDER_TEST",
                "NATIVE_MUTATION_REPORT_DIR",
            }:
                environment.pop(name)
        environment.update(TMPDIR=str(directory), TMP=str(directory), TEMP=str(directory))
        command(
            [sys.executable, "-m", "mutmut", "run", "--max-children", "2", *TARGETS],
            directory=directory,
            environment=environment,
        )
        results = command(
            [sys.executable, "-m", "mutmut", "results", "--all", "true"],
            directory=directory,
            environment=environment,
            capture=True,
        )
        selected = {}
        for line in results.splitlines():
            name, separator, status = line.strip().partition(": ")
            if separator and any(fnmatch.fnmatchcase(name, pattern) for pattern in TARGETS):
                selected[name] = status
        if (
            not selected
            or any(status not in {"killed", "survived"} for status in selected.values())
            or any(
                not any(fnmatch.fnmatchcase(name, pattern) for name in selected)
                for pattern in TARGETS
            )
        ):
            raise SystemExit("campaign has missing or inconclusive mutation evidence")
        survivor_diffs = {}
        for name, status in selected.items():
            if status == "survived":
                shown = command(
                    [sys.executable, "-m", "mutmut", "show", name],
                    directory=directory,
                    environment=environment,
                    capture=True,
                )
                survivor_diffs[name] = shown
        hashes = {
            str(path.relative_to(repository)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((repository / "src/librus_mcp").glob("*.py"))
        }
        evidence = {
            "mutmut": "3.7.0",
            "python": sys.version.split()[0],
            "targets": TARGETS,
            "source_sha256": hashes,
            "counts": dict(Counter(selected.values())),
            "results": selected,
            "survivor_diffs": survivor_diffs,
            "input_sha256": {
                str(path.relative_to(repository)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(
                    [
                        repository / "pyproject.toml",
                        repository / "uv.lock",
                        Path(__file__).resolve(),
                    ]
                    + list((repository / "tests_native").glob("*.py"))
                )
            },
        }
        if report is not None:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        print(json.dumps(evidence["counts"], sort_keys=True))
        if baseline is not None:
            reviewed = json.loads(baseline.read_text(encoding="utf-8"))
            if (
                reviewed["mutmut"] != evidence["mutmut"]
                or reviewed["targets"] != list(TARGETS)
                or set(reviewed["results"]) != set(selected)
                or any(
                    reviewed["survivor_diffs"].get(name) != diff
                    for name, diff in survivor_diffs.items()
                )
            ):
                raise SystemExit("new/changed mutation outcomes require review; inspect the report")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path, help="retain campaign evidence outside disposable scratch"
    )
    parser.add_argument("--check-baseline", type=Path, help="reject new or changed survivors")
    arguments = parser.parse_args()
    if arguments.report and arguments.check_baseline:
        if arguments.report.resolve() == arguments.check_baseline.resolve():
            parser.error("report must not overwrite the reviewed baseline")

    def interrupted(signum, frame):
        raise SystemExit(f"mutation campaign interrupted by signal {signum}")

    if os.name == "posix":
        for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, interrupted)
    run(arguments.report, arguments.check_baseline)


if __name__ == "__main__":
    main()
