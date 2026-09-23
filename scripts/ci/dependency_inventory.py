"""Enumerate every declared dependency scope from this repository's lockfiles.

The CycloneDX SBOM is produced from an installed environment, so it can only
describe what that environment happened to contain: the `dev`, `fuzz` and
`native-build` groups, the Rust workspace and the npm tree are outside it, while
the SBOM generator's own CI tools are inside it. Scoping the release SBOM down
to the shipped artefact does not discharge the licence policy -- the excluded
classes still have to be adjudicated -- so this emits them as a separate,
explicitly scoped inventory bound to the same commit.

Input is the lockfiles alone: `uv.lock`, `rust/Cargo.lock`, `package-lock.json`.
Nothing is installed, resolved or fetched, so this runs anywhere the repository
is checked out, and the inventory is the resolved transitive closure rather than
a sample of it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


def _toml_packages(path: Path) -> list[dict[str, str]]:
    with open(path, "rb") as handle:
        document = tomllib.load(handle)
    return [
        {"name": str(entry["name"]), "version": str(entry.get("version", ""))}
        for entry in document.get("package") or []
        if isinstance(entry, dict) and entry.get("name")
    ]


def _npm_packages(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    packages: list[dict[str, str]] = []
    for location, entry in (document.get("packages") or {}).items():
        if not location or not isinstance(entry, dict):
            continue  # the "" key is the project itself
        name = entry.get("name") or location.split("node_modules/", 1)[-1]
        packages.append({"name": str(name), "version": str(entry.get("version", ""))})
    return packages


def _source_sha(repository_root: Path) -> str:
    """The commit this inventory describes, so it can be bound to an SBOM."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return completed.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def build_inventory(repository_root: Path) -> dict[str, Any]:
    """Collect every lockfile-resolved dependency, grouped by ecosystem."""
    ecosystems: list[dict[str, Any]] = []
    for ecosystem, lock, reader, purl_prefix in (
        ("python", repository_root / "uv.lock", _toml_packages, "pkg:pypi/"),
        ("cargo", repository_root / "rust" / "Cargo.lock", _toml_packages, "pkg:cargo/"),
        ("npm", repository_root / "package-lock.json", _npm_packages, "pkg:npm/"),
    ):
        entry: dict[str, Any] = {"ecosystem": ecosystem, "lockfile": str(lock.relative_to(repository_root))}
        if not lock.exists():
            entry["error"] = "lockfile absent, so this scope is unprovable"
            entry["packages"] = []
            ecosystems.append(entry)
            continue
        packages = reader(lock)
        for package in packages:
            package["purl"] = f"{purl_prefix}{package['name']}@{package['version']}"
        entry["packages"] = sorted(packages, key=lambda package: (package["name"], package["version"]))
        ecosystems.append(entry)
    return {
        "schema": "contextual-orchestrator/dependency-inventory/v1",
        "source_sha": _source_sha(repository_root),
        "scope_note": (
            "Lockfile-resolved closure for every declared scope, including the classes a release "
            "SBOM built from an installed environment cannot see. Licence adjudication of these "
            "entries is required; exclusion from the shipped artefact is not an exemption."
        ),
        "ecosystems": ecosystems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the lockfile-resolved dependency inventory.")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    root = Path(arguments.repository_root).resolve()
    try:
        inventory = build_inventory(root)
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"::error::Dependency inventory could not be built ({error}).", file=sys.stderr)
        return 1
    with open(arguments.output, "w", encoding="utf-8") as handle:
        json.dump(inventory, handle, indent=2, sort_keys=True)
        handle.write("\n")
    counts = ", ".join(
        f"{entry['ecosystem']}={len(entry['packages'])}" for entry in inventory["ecosystems"]
    )
    print(f"dependency inventory written to {arguments.output} for {inventory['source_sha'][:12]}: {counts}")
    unprovable = [entry["ecosystem"] for entry in inventory["ecosystems"] if entry.get("error")]
    if unprovable:
        print(f"::error::Unprovable dependency scopes: {', '.join(unprovable)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
