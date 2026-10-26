#!/usr/bin/env python3
"""Build the MCP Bundle (.mcpb) around a verified wheel.

The bundle carries that exact wheel and a uv.lock resolved under the project's
quarantine cutoff, so the host installs the same dependency versions that the
release qualified, not a fresh resolution.
"""

import argparse
import json
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# A fixed timestamp keeps the archive byte-identical for the same inputs.
EPOCH = (2026, 1, 1, 0, 0, 0)


class BundleError(RuntimeError):
    """The bundle cannot be built from these inputs."""


def _toml_string(value: str) -> str:
    return json.dumps(value)


def qualified_pins() -> list[str]:
    """The runtime closure exactly as uv.lock resolved it for the release."""
    exported = subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes"]
        + ["--no-annotate", "--no-header", "--format", "requirements-txt"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line.strip() for line in exported.splitlines() if line.strip()]


def bundle_pyproject(
    version: str, wheel_name: str, quarantine: dict[str, Any], pins: list[str]
) -> str:
    packages = ", ".join(
        f"{json.dumps(name)} = {_toml_string(cutoff)}"
        for name, cutoff in quarantine.get("exclude-newer-package", {}).items()
    )
    constraints = "".join(f"\n    {_toml_string(pin)}," for pin in pins)
    return f"""[project]
name = "librus-mcp-bundle"
version = "{version}"
requires-python = "==3.14.*"
dependencies = ["librus-mcp=={version}"]

[tool.uv]
exclude-newer = {_toml_string(quarantine["exclude-newer"])}
exclude-newer-package = {{ {packages} }}
constraint-dependencies = [{constraints}
]

[tool.uv.sources]
librus-mcp = {{ path = "wheels/{wheel_name}" }}
"""


def locked_versions(lock_file: Path) -> dict[str, str]:
    with lock_file.open("rb") as file:
        lock = tomllib.load(file)
    return {package["name"]: package["version"] for package in lock["package"]}


def build(wheel: Path, out_dir: Path) -> Path:
    with (ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)
    version = project["project"]["version"]
    if not wheel.name.startswith(f"librus_mcp-{version}-"):
        raise BundleError(f"{wheel.name} is not the librus-mcp {version} wheel")
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary)
        manifest = json.loads((ROOT / "mcpb" / "manifest.json").read_text(encoding="utf-8"))
        manifest["version"] = version
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        shutil.copytree(ROOT / "mcpb" / "src", stage / "src")
        (stage / "wheels").mkdir()
        shutil.copy(wheel, stage / "wheels" / wheel.name)
        # The locked closure has 3.14 wheels; a newer host Python would build from source.
        (stage / ".python-version").write_text("3.14\n")
        (stage / "pyproject.toml").write_text(
            bundle_pyproject(version, wheel.name, project["tool"]["uv"], qualified_pins())
        )
        subprocess.run(["uv", "lock", "--quiet", "--directory", str(stage)], check=True)
        # Every shared dependency must resolve exactly as the qualified project lock.
        project_versions = locked_versions(ROOT / "uv.lock")
        drift = sorted(
            name
            for name, locked in locked_versions(stage / "uv.lock").items()
            if name in project_versions and project_versions[name] != locked
        )
        if drift:
            raise BundleError("bundle lock differs from uv.lock for " + ", ".join(drift))
        out_dir.mkdir(parents=True, exist_ok=True)
        bundle = out_dir / f"librus-mcp-{version}.mcpb"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(p for p in stage.rglob("*") if p.is_file()):
                if "__pycache__" in path.parts:
                    continue
                info = zipfile.ZipInfo(path.relative_to(stage).as_posix(), EPOCH)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True, help="verified librus-mcp wheel")
    parser.add_argument("--out-dir", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        bundle = build(arguments.wheel.resolve(), arguments.out_dir)
    except (BundleError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"bundle build failed: {error}") from None
    print(bundle)


if __name__ == "__main__":
    main()
