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
import email
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Any


_NAME_SEPARATORS = re.compile(r"[-_.]+")


class InventoryError(Exception):
    """A lockfile could not be read as a complete dependency set."""


def _toml_packages(path: Path, data: bytes) -> list[dict[str, str]]:
    """Read ``[[package]]`` entries, refusing to drop any of them quietly.

    Skipping a malformed or nameless entry would shrink the inventory without
    saying so, which is the failure this file exists to prevent.
    """
    document = tomllib.loads(data.decode("utf-8"))
    packages: list[dict[str, str]] = []
    for index, entry in enumerate(document.get("package") or []):
        if not isinstance(entry, dict) or not entry.get("name") or not entry.get("version"):
            raise InventoryError(f"{path}: package[{index}] is malformed or has no name/version")
        packages.append({"name": str(entry["name"]), "version": str(entry["version"])})
    return packages


def _npm_packages(path: Path, data: bytes) -> list[dict[str, str]]:
    document = json.loads(data.decode("utf-8"))
    packages: list[dict[str, str]] = []
    for location, entry in (document.get("packages") or {}).items():
        if not location:
            continue  # the "" key is the project itself, not a dependency
        if not isinstance(entry, dict):
            # Skipping it would let a file with one good and one broken entry
            # report only the good one, which is the silence this refuses.
            raise InventoryError(f"{path}: entry {location!r} is not an object")
        # A nested path is "node_modules/a/node_modules/b": the package is the
        # segment after the LAST marker, not everything after the first one.
        name = entry.get("name") or location.rsplit("node_modules/", 1)[-1]
        version = entry.get("version")
        if not name or not version:
            raise InventoryError(f"{path}: entry {location!r} has no resolvable name/version")
        packages.append({"name": str(name), "version": str(version)})
    return packages


_PNPM_SUPPORTED_VERSIONS = frozenset({"9", "9.0"})


def _pnpm_packages(path: Path, data: bytes) -> list[dict[str, str]]:
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
    lines = data.decode("utf-8").splitlines()
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


_EXTERNAL_SOURCE = re.compile(
    r"^\s*(?:--(?:find-links|index-url|extra-index-url)\b|-[fi]\s)|@\s*(?:git\+|https?://|file://)",
)


def external_source_findings(path: Path, data: bytes) -> list[str]:
    """Requirements that reach outside the hash-pinned index set.

    `--no-index` only stops pip consulting an index. A direct URL, a VCS
    requirement or an extra find-links line in the file itself is still
    fetched, and a VCS requirement is built from source, which executes the
    package's own build code. Those cannot be adjudicated from a downloaded
    wheel, so they are reported rather than silently trusted.
    """
    findings: list[str] = []
    for number, line in enumerate(data.decode("utf-8").splitlines(), start=1):
        if line.lstrip().startswith("#") or not line.strip():
            continue
        if _EXTERNAL_SOURCE.search(line):
            findings.append(f"{path.name}:{number}: {line.strip()[:120]}")
    return findings


def _requirements_packages(path: Path, data: bytes) -> list[dict[str, str]]:
    """Read pinned ``name==version`` lines from a hash-locked requirements file."""
    packages: list[dict[str, str]] = []
    for line in data.decode("utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)", line)
        if match:
            packages.append({"name": match.group(1), "version": match.group(2)})
    return packages


def _artifact_license_terms(
    artifact_dir: Path, name: str, version: str
) -> tuple[list[str], str, list[str]]:
    """Read a package's licence from its own distribution artefact, unopened.

    The artefact is the evidence: its `.dist-info/METADATA` and bundled licence
    files state the terms the publisher shipped. Reading them from the archive
    is a file read -- the package is never installed, imported or executed --
    and the artefact's sha256 is recorded so the licence is tied to the exact
    bytes, not to a registry's separate claim about them.
    """
    normalized = _NAME_SEPARATORS.sub("_", name.strip().lower())
    candidates = sorted(artifact_dir.glob(f"{normalized}-{version}*.whl"))
    if not candidates:
        # sdists are excluded on purpose: reading one usefully means running its
        # build backend, and an unreviewed package must not execute here.
        return [], f"no wheel for {name}=={version} in {artifact_dir}", []
    artifact = candidates[0]
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    terms: list[str] = []
    license_files: list[str] = []
    with zipfile.ZipFile(artifact) as archive:
        for member in archive.namelist():
            if member.endswith(".dist-info/METADATA") and not terms:
                metadata = email.message_from_string(archive.read(member).decode("utf-8", "replace"))
                terms = _metadata_license_terms(metadata)
            elif ".dist-info/" in member and Path(member).name.upper().startswith(
                ("LICENSE", "LICENCE", "COPYING", "NOTICE")
            ):
                raw = archive.read(member)
                license_files.append({
                    "name": Path(member).name,
                    # Hash the bytes as shipped: decoding and re-encoding would
                    # hash a normalised copy, not the instrument itself.
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "text": raw.decode("utf-8", "replace"),
                })
    if not terms:
        return [], f"{artifact.name} (sha256 {digest[:12]}) declares no licence metadata", license_files
    # The declaration is what the publisher stated; the bundled licence text is
    # the instrument itself. Absence of the text is recorded, never resolved by
    # the declaration alone.
    evidence = (
        "licence files: " + ", ".join(sorted(entry["name"] for entry in license_files))
        if license_files
        else "declaration only: the wheel bundles no licence text"
    )
    return terms, f"artefact {artifact.name} sha256 {digest}; {evidence}", license_files


def _metadata_license_terms(metadata: Any) -> list[str]:
    """Licence terms declared by one distribution's METADATA, in SPDX-first order."""
    terms: list[str] = []
    expression = (metadata.get("License-Expression") or "").strip()
    if expression:
        terms.append(expression)
    declared = (metadata.get("License") or "").strip()
    if declared and len(declared) <= 120:
        terms.append(declared.splitlines()[0])
    terms += [
        classifier.split("::")[-1].strip()
        for classifier in metadata.get_all("Classifier") or []
        if classifier.startswith("License ::")
    ]
    return terms


def _installed_license_terms(name: str, version: str) -> tuple[list[str], str]:
    """Read one distribution's licence terms from metadata already on disk.

    The job that runs this has already installed the shipped set, so its
    `.dist-info/METADATA` files are preserved evidence that can be read without
    installing anything further. Reading them is a file read: no package code
    is imported or executed. A distribution that is not present, or is present
    at another version, yields nothing rather than a guess.
    """
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return [], "absent from this environment"
    metadata = distribution.metadata
    if str(metadata.get("Version") or "") != version:
        return [], f"environment holds {metadata.get('Version')!r}, not the locked version"
    return _metadata_license_terms(metadata), "installed distribution metadata"


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


def _read_locked_source(repository_root: Path, lock: Path, commit: str) -> tuple[bytes, dict[str, Any]]:
    """Bind the inventory to the exact bytes read, not merely to a commit name.

    A commit id describes what is committed; the reader may have read something
    else. Recording the read bytes' hash beside the committed blob's hash makes
    a modified working tree visible instead of silently inventorying bytes that
    no release can reproduce.
    """
    data = lock.read_bytes()
    relative = str(lock.relative_to(repository_root))
    provenance: dict[str, Any] = {"path": relative, "read_sha256": hashlib.sha256(data).hexdigest()}
    try:
        # Hash the bytes already in hand rather than letting git re-read the
        # path: three separate reads could bind three different files.
        completed = subprocess.run(
            ["git", "-C", str(repository_root), "hash-object", "--stdin"],
            input=data, capture_output=True, check=True,
        )
        provenance["blob_id"] = completed.stdout.decode().strip()
        provenance["committed_blob_id"] = _git(repository_root, "rev-parse", f"{commit}:{relative}")
    except (OSError, subprocess.CalledProcessError):
        provenance["error"] = "git could not resolve the committed blob for this file"
        return data, provenance
    provenance["matches_commit"] = provenance["blob_id"] == provenance["committed_blob_id"]
    return data, provenance


def build_inventory(
    repository_root: Path, resolve_licenses: bool = False, artifact_dir: Path | None = None
) -> dict[str, Any]:
    """Collect every lockfile-resolved dependency, grouped by ecosystem."""
    # One commit is captured up front and every blob comparison uses it, so a
    # branch moving mid-run cannot bind half the inventory to another tree.
    commit = _source_sha(repository_root)
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
        data, provenance = _read_locked_source(repository_root, lock, commit)
        entry["provenance"] = [provenance]
        packages = reader(lock, data)
        for package in packages:
            package["sources"] = [provenance["path"]]
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
                requirements_data, requirements_provenance = _read_locked_source(
                    repository_root, requirements, commit
                )
                entry["provenance"].append(requirements_provenance)
                index = {(package["name"], package["version"]): package for package in packages}
                entry.setdefault("external_sources", []).extend(
                    external_source_findings(requirements, requirements_data)
                )
                for package in _requirements_packages(requirements, requirements_data):
                    key = (package["name"], package["version"])
                    known = index.get(key)
                    if known is not None:
                        # The same pin in two consumed files is one package with
                        # two consumers, not a duplicate to drop.
                        known["sources"].append(requirements_provenance["path"])
                        continue
                    package["sources"] = [requirements_provenance["path"]]
                    index[key] = package
                    packages.append(package)
        if ecosystem == "npm":
            pnpm_lock = repository_root / "pnpm-lock.yaml"
            if pnpm_lock.exists():
                entry["lockfile"] = f"{entry['lockfile']}, {pnpm_lock.relative_to(repository_root)}"
                pnpm_data, pnpm_provenance = _read_locked_source(repository_root, pnpm_lock, commit)
                entry["provenance"].append(pnpm_provenance)
                index = {(package["name"], package["version"]): package for package in packages}
                for package in _pnpm_packages(pnpm_lock, pnpm_data):
                    key = (package["name"], package["version"])
                    known = index.get(key)
                    if known is not None:
                        known["sources"].append(pnpm_provenance["path"])
                        continue
                    package["sources"] = [pnpm_provenance["path"]]
                    index[key] = package
                    packages.append(package)
        for package in packages:
            package["purl"] = f"{purl_prefix}{package['name']}@{package['version']}"
        if ecosystem == "python" and resolve_licenses:
            for package in packages:
                if artifact_dir is not None:
                    terms, source, license_files = _artifact_license_terms(
                        artifact_dir, package["name"], package["version"]
                    )
                else:
                    terms, source = _installed_license_terms(package["name"], package["version"])
                    license_files = []
                package["licenses"] = terms
                package["license_files"] = license_files
                package["license_source"] = source if terms else f"unresolved: {source}"
        entry["packages"] = sorted(packages, key=lambda package: (package["name"], package["version"]))
        ecosystems.append(entry)
    return {
        "schema": "contextual-orchestrator/dependency-inventory/v1",
        "source_sha": commit,
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
    parser.add_argument(
        "--resolve-licenses", action="store_true",
        help="attach licence terms read from distribution metadata already installed in this job",
    )
    parser.add_argument(
        "--check-sources-only", action="store_true",
        help="report requirements that reach outside the hash-pinned wheel set, and stop",
    )
    parser.add_argument(
        "--artifact-dir",
        help="read licences from downloaded distribution artefacts here instead of installed metadata",
    )
    arguments = parser.parse_args(argv)
    root = Path(arguments.repository_root).resolve()
    if arguments.check_sources_only:
        findings: list[str] = []
        for candidate in sorted(root.glob("requirements*.txt")) + sorted(
            (root / "fuzz").glob("requirements*.txt")
        ) + [root / "requirements.lock"]:
            if candidate.exists():
                findings += external_source_findings(candidate, candidate.read_bytes())
        for finding in findings:
            print(f"::error::Requirement reaches outside the hash-pinned wheel set: {finding}",
                  file=sys.stderr)
        print(f"source check: {len(findings)} external requirement(s)")
        return 1 if findings else 0
    try:
        inventory = build_inventory(
            root,
            resolve_licenses=arguments.resolve_licenses or bool(arguments.artifact_dir),
            artifact_dir=Path(arguments.artifact_dir).resolve() if arguments.artifact_dir else None,
        )
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
        for external in entry.get("external_sources") or []:
            problems.append(
                f"{ecosystem}: {external} reaches outside the hash-pinned wheel set, so its licence "
                "cannot be adjudicated from a downloaded artefact"
            )
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
