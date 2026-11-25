#!/usr/bin/env python3
"""Ratchet for code comments and tests marked for deletion (Python 3.10+).

Counts, per tracked Python file under the configured roots:

- comments: comment lines from the tokenizer, except tool pragmas and one-line
  `# Why: ...` comments;
- to_delete: `pytest.mark.to_delete(issue=N)` markers.

Both counts may only fall. The baseline is a JSON file committed to the
repository; a file missing from it has a baseline of zero.

  audit_ratchet.py init  --roots src tests   write the first baseline
  audit_ratchet.py check                     fail when any count rose, or fell
                                             without the baseline lowered
  audit_ratchet.py update                    lower the baseline to the
                                             current counts; refuses a rise
  audit_ratchet.py report                    totals and the largest files

Options: --baseline PATH (default .agents/audit-baseline.json).
Copy this file into the project (scripts/audit_ratchet.py) and run `check`
in CI. Standard library only.
"""

import argparse
import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any

VERSION = 1
DEFAULT_BASELINE = ".agents/audit-baseline.json"
KINDS = ("comments", "to_delete")
Counts = dict[str, dict[str, int]]
PRAGMA = re.compile(
    r"^#\s*(noqa\b|type:\s*ignore|pragma:|pyright:|mypy:|fmt:|isort:|ruff:|nosec\b|pylint:)"
)
CODING = re.compile(r"^#.*coding[:=]")
WHY = re.compile(r"^#\s*Why:\s*\S")


class RatchetError(Exception):
    pass


def count_comments(source: str) -> int:
    total = 0
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        text = tok.string
        line = tok.start[0]
        if line == 1 and text.startswith("#!"):
            continue
        if line <= 2 and CODING.match(text):
            continue
        if PRAGMA.match(text) or WHY.match(text):
            continue
        total += 1
    return total


def dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def count_to_delete(source: str, path: str) -> int:
    tree = ast.parse(source, filename=path)
    total = 0
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and dotted(node.func).endswith("mark.to_delete"):
            calls.add(id(node.func))
            issue = next((k.value for k in node.keywords if k.arg == "issue"), None)
            if not (
                isinstance(issue, ast.Constant)
                and isinstance(issue.value, int)
                and not isinstance(issue.value, bool)
                and issue.value > 0
            ):
                raise RatchetError(f"{path}:{node.lineno}: to_delete needs issue=<issue number>")
            total += 1
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "to_delete"
            and dotted(node).endswith("mark.to_delete")
            and id(node) not in calls
        ):
            raise RatchetError(f"{path}:{node.lineno}: to_delete needs issue=<issue number>")
    return total


def tracked_files(roots: list[str]) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", *roots], capture_output=True, check=True
        ).stdout.decode()
        files = [f for f in out.split("\0") if f.endswith(".py")]
    except OSError, subprocess.CalledProcessError:
        files = [str(p) for r in roots for p in Path(r).rglob("*.py")]
    return sorted(f for f in files if Path(f).is_file())


def measure(roots: list[str]) -> Counts:
    counts: Counts = {kind: {} for kind in KINDS}
    for path in tracked_files(roots):
        source = Path(path).read_text(encoding="utf-8")
        found = {
            "comments": count_comments(source),
            "to_delete": count_to_delete(source, path),
        }
        for kind in KINDS:
            if found[kind]:
                counts[kind][path] = found[kind]
    return counts


def load(path: str) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RatchetError(f"no baseline at {path}; run init first") from None
    if data.get("version") != VERSION or not data.get("roots"):
        raise RatchetError(f"{path}: unsupported baseline (version {VERSION} with roots)")
    return data


def save(path: str, roots: list[str], counts: Counts) -> None:
    data: dict[str, Any] = {"version": VERSION, "roots": roots}
    data.update({kind: dict(sorted(counts[kind].items())) for kind in KINDS})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def rises(baseline: dict[str, Any], counts: Counts) -> list[str]:
    out: list[str] = []
    for kind in KINDS:
        old = baseline.get(kind, {})
        for path, n in counts[kind].items():
            if n > old.get(path, 0):
                out.append(f"{kind}: {path} has {n}, baseline {old.get(path, 0)}")
    return out


def falls(baseline: dict[str, Any], counts: Counts) -> int:
    return sum(
        1
        for kind in KINDS
        for path, n in baseline.get(kind, {}).items()
        if counts[kind].get(path, 0) < n
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("init", "check", "update", "report"))
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--roots", nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            if Path(args.baseline).exists():
                raise RatchetError(f"{args.baseline} exists; use update")
            if not args.roots:
                raise RatchetError("init needs --roots")
            counts = measure(args.roots)
            save(args.baseline, args.roots, counts)
            print(
                f"wrote {args.baseline}: "
                + ", ".join(f"{sum(counts[k].values())} {k}" for k in KINDS)
            )
            return 0
        baseline = load(args.baseline)
        roots = baseline["roots"]
        counts = measure(roots)
        up = rises(baseline, counts)
        if args.command == "report":
            for kind in KINDS:
                top = sorted(counts[kind].items(), key=lambda kv: -kv[1])[:10]
                print(f"{kind}: {sum(counts[kind].values())} in {len(counts[kind])} files")
                for path, n in top:
                    print(f"  {n:5d}  {path}")
            return 0
        if up:
            print("audit ratchet: counts rose above the baseline:", file=sys.stderr)
            for line in up:
                print(f"  {line}", file=sys.stderr)
            print(
                "Remove the new comment or marker. A one-line `# Why: ...` comment "
                "and tool pragmas are not counted.",
                file=sys.stderr,
            )
            return 1
        if args.command == "update":
            save(args.baseline, roots, counts)
            print(f"lowered {args.baseline}")
            return 0
        lower = falls(baseline, counts)
        if lower:
            # Lock in every fall, so a later change cannot spend the headroom.
            print(
                f"audit ratchet: {lower} counts fell below the baseline; run "
                f"`audit_ratchet.py update` and commit {args.baseline}",
                file=sys.stderr,
            )
            return 1
        print("audit ratchet: ok")
        return 0
    except (RatchetError, SyntaxError, UnicodeDecodeError) as error:
        print(f"audit ratchet: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
