"""Enumerate every declared dependency scope from this repository's lockfiles.

The CycloneDX SBOM is produced from an installed environment, so it can only
describe what that environment happened to contain: the `dev`, `fuzz` and
`native-build` groups, the Rust workspace and the npm tree are outside it, while
the SBOM generator's own CI tools are inside it. Scoping the release SBOM down
to the shipped artefact does not discharge the licence policy -- the excluded
classes still have to be adjudicated -- so this emits them as a separate,
explicitly scoped inventory bound to the same commit.

Input is the pinned files alone: `uv.lock` plus every `requirements*.txt` (the
CI and fuzz toolchains), `rust/Cargo.lock`, and both npm lockfiles
(`package-lock.json` and `pnpm-lock.yaml`, whose trees differ). Each source is
named in the output, because the union of the files read is what this can
prove -- it is not a claim that nothing else is declared anywhere.
Nothing is installed, resolved or fetched, so this runs anywhere the repository
is checked out, and the inventory is the resolved transitive closure rather than
a sample of it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


class InventoryError(Exception):
    """A lockfile could not be read as a complete dependency set."""


def _toml_packages(path: Path) -> list[dict[str, str]]:
    """Read ``[[package]]`` entries, refusing to drop any of them quietly.

    Skipping a malformed or nameless entry would shrink the inventory without
    saying so, which is the failure this file exists to prevent.
    """
    with open(path, "rb") as handle:
        document = tomllib.load(handle)
    packages: list[dict[str, str]] = []
    for index, entry in enumerate(document.get("package") or []):
        if not isinstance(entry, dict) or not entry.get("name") or not entry.get("version"):
            raise InventoryError(f"{path}: package[{index}] is malformed or has no name/version")
        packages.append({"name": str(entry["name"]), "version": str(entry["version"])})
    return packages


def _npm_packages(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    packages: list[dict[str, str]] = []
    for location, entry in (document.get("packages") or {}).items():
        if not location or not isinstance(entry, dict):
            continue  # the "" key is the project itself
        # A nested path is "node_modules/a/node_modules/b": the package is the
        # segment after the LAST marker, not everything after the first one.
        name = entry.get("name") or location.rsplit("node_modules/", 1)[-1]
        version = entry.get("version")
        if not name or not version:
            raise InventoryError(f"{path}: entry {location!r} has no resolvable name/version")
        packages.append({"name": str(name), "version": str(version)})
    return packages


_PNPM_SUPPORTED_VERSIONS = frozenset({"9", "9.0"})


def _pnpm_packages(path: Path) -> list[dict[str, str]]:
    """Read the `packages:` block of a pnpm v9 lockfile.

    Each key is ``name@version``, quoted when it carries a scope, which is all
    this inventory needs, so the bounded block is read directly instead of
    adding a YAML dependency for it. A scoped name splits on its last ``@`` so
    ``@scope/name@1.2.3`` survives.

    Only lockfile version 9 is read. Older layouts key packages differently --
    v6 writes ``/name@1.0.0(peer@2.0.0)``, whose peer suffix would be recorded
    as part of the version -- and a future layout is unknown by definition, so
    anything else fails closed rather than producing plausible nonsense.
    """
    declared_version = ""
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        match = re.match(r"^lockfileVersion:\s*'?\"?([0-9.]+)'?\"?\s*$", line)
        if match:
            declared_version = match.group(1)
            break
    if declared_version not in _PNPM_SUPPORTED_VERSIONS:
        raise InventoryError(
            f"{path}: lockfileVersion {declared_version or '<absent>'} is not a layout this inventory "
            f"reads (supported: {', '.join(sorted(_PNPM_SUPPORTED_VERSIONS))})"
        )
    packages: list[dict[str, str]] = []
    inside = False
    for line in lines:
        if not line.strip():
            continue
        if not line.startswith(" "):
            inside = line.startswith("packages:")
            continue
        if not inside:
            continue
        # Exactly two spaces of indent: deeper lines are a package's own
        # fields (resolution, engines, peerDependencies), not package keys.
        match = re.match(r"""^  (?P<quote>['"]?)(?P<spec>[^\s'"].*?)(?P=quote):\s*$""", line)
        if not match:
            continue
        spec = match.group("spec")
        name, separator, version = spec.rpartition("@")
        if not separator or not name or not version:
            raise InventoryError(f"{path}: package key {spec!r} has no name@version form")
        packages.append({"name": name, "version": version})
    return packages


def _requirements_packages(path: Path) -> list[dict[str, str]]:
    """Read pinned ``name==version`` lines from a hash-locked requirements file."""
    packages: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)", line)
        if match:
            packages.append({"name": match.group(1), "version": match.group(2)})
    return packages


def _git(repository_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), *arguments],
        capture_output=True, text=True, check=True,
    )
    return completed.stdout.strip()


def _source_sha(repository_root: Path) -> str:
    """The commit this inventory describes, so it can be bound to an SBOM."""
    try:
        return _git(repository_root, "rev-parse", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        return ""


def _lock_provenance(repository_root: Path, lock: Path) -> dict[str, Any]:
    """Bind the inventory to the exact bytes read, not merely to a commit name.

    A commit id describes what is committed; the reader may have read something
    else. Recording the read bytes' hash beside the committed blob's hash makes
    a modified working tree visible instead of silently inventorying bytes that
    no release can reproduce.
    """
    data = lock.read_bytes()
    read_hash = hashlib.sha256(data).hexdigest()
    relative = str(lock.relative_to(repository_root))
    provenance: dict[str, Any] = {"path": relative, "read_sha256": read_hash}
    try:
        provenance["blob_id"] = _git(repository_root, "hash-object", str(lock))
        provenance["committed_blob_id"] = _git(repository_root, "rev-parse", f"HEAD:{relative}")
    except (OSError, subprocess.CalledProcessError):
        provenance["error"] = "git could not resolve the committed blob for this lockfile"
        return provenance
    provenance["matches_commit"] = provenance["blob_id"] == provenance["committed_blob_id"]
    return provenance


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
        entry["provenance"] = [_lock_provenance(repository_root, lock)]
        packages = reader(lock)
        if ecosystem == "python":
            # uv.lock resolves the project's own scopes; the CI and fuzz
            # toolchains are pinned in their own hash-locked requirements
            # files, and those install into the same jobs, so they belong in
            # the enumeration rather than outside it.
            pinned_files = sorted(repository_root.glob("requirements*.txt"))
            pinned_files += sorted((repository_root / "fuzz").glob("requirements*.txt"))
            if (repository_root / "requirements.lock").exists():
                pinned_files.insert(0, repository_root / "requirements.lock")
            for requirements in pinned_files:
                entry["lockfile"] = f"{entry['lockfile']}, {requirements.relative_to(repository_root)}"
                entry["provenance"].append(_lock_provenance(repository_root, requirements))
                seen = {(package["name"], package["version"]) for package in packages}
                packages += [
                    package
                    for package in _requirements_packages(requirements)
                    if (package["name"], package["version"]) not in seen
                ]
        if ecosystem == "npm":
            pnpm_lock = repository_root / "pnpm-lock.yaml"
            if pnpm_lock.exists():
                entry["lockfile"] = f"{entry['lockfile']}, {pnpm_lock.relative_to(repository_root)}"
                entry["provenance"].append(_lock_provenance(repository_root, pnpm_lock))
                seen = {(package["name"], package["version"]) for package in packages}
                packages += [
                    package
                    for package in _pnpm_packages(pnpm_lock)
                    if (package["name"], package["version"]) not in seen
                ]
        for package in packages:
            package["purl"] = f"{purl_prefix}{package['name']}@{package['version']}"
        entry["packages"] = sorted(packages, key=lambda package: (package["name"], package["version"]))
        ecosystems.append(entry)
    return {
        "schema": "contextual-orchestrator/dependency-inventory/v1",
        "source_sha": _source_sha(repository_root),
        "scope_note": (
            "Union of the lockfiles and pinned requirement files enumerated in each ecosystem's "
            "'lockfile' field, which is what this inventory can prove -- not an assertion that the "
            "repository declares nothing else. It deliberately includes classes a release SBOM built "
            "from one installed environment cannot see. Licence adjudication of these entries is "
            "required; exclusion from the shipped artefact is not an exemption."
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
    except (InventoryError, OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"::error::Dependency inventory could not be built ({error}).", file=sys.stderr)
        return 1
    with open(arguments.output, "w", encoding="utf-8") as handle:
        json.dump(inventory, handle, indent=2, sort_keys=True)
        handle.write("\n")
    counts = ", ".join(
        f"{entry['ecosystem']}={len(entry['packages'])}" for entry in inventory["ecosystems"]
    )
    print(f"dependency inventory written to {arguments.output} for {inventory['source_sha'][:12]}: {counts}")
    problems: list[str] = []
    if not inventory["source_sha"]:
        problems.append("no source commit could be resolved, so nothing can be bound to an SBOM")
    for entry in inventory["ecosystems"]:
        ecosystem = entry["ecosystem"]
        if entry.get("error"):
            problems.append(f"{ecosystem}: {entry['error']}")
            continue
        if not entry["packages"]:
            # An empty set is silence about the scope, never a clean one.
            problems.append(f"{ecosystem}: {entry['lockfile']} resolved no packages")
        for provenance in entry.get("provenance") or []:
            if provenance.get("error"):
                problems.append(f"{ecosystem}: {provenance['path']}: {provenance['error']}")
            elif not provenance.get("matches_commit"):
                problems.append(
                    f"{ecosystem}: {provenance['path']} read bytes {provenance['read_sha256'][:12]} "
                    f"do not match the committed blob, so this inventory describes an unreproducible tree"
                )
    if problems:
        for problem in problems:
            print(f"::error::Dependency inventory refused: {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
