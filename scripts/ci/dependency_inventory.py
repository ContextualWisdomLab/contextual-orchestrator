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
Nothing is installed or executed. Optional native archive downloads are digest-verified
and restricted to canonical registries. This runs anywhere the repository
is checked out, and the inventory is the resolved transitive closure rather than
a sample of it.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import email
import hashlib
import importlib.metadata
import io
import json
import re
import subprocess
import sys
import tarfile
import tomllib
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
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
        package = {"name": str(entry["name"]), "version": str(entry["version"])}
        if path.name == "uv.lock" and entry.get("source") in ({"editable": "."}, {"virtual": "."}):
            package["source"] = entry["source"]
        if path.name == "Cargo.lock":
            package.update({key: entry[key] for key in ("source", "checksum") if key in entry})
        packages.append(package)
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
        package = {"name": str(name), "version": str(version)}
        package.update({key: entry[key] for key in ("resolved", "integrity") if key in entry})
        packages.append(package)
    return packages


_PNPM_SUPPORTED_VERSIONS = frozenset({"9", "9.0"})


def _pnpm_packages(path: Path, data: bytes) -> list[dict[str, str]]:
    """Read the `packages:` block of a pnpm v9 lockfile.

    Each key is ``name@version``, quoted when it carries a scope. The inline
    resolution integrity is retained for native archive verification. The
    bounded block is read directly instead of
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
            integrity = re.fullmatch(r"    resolution: \{integrity: ([^ ,}]+)\}\s*", line)
            if integrity and packages:
                packages[-1]["integrity"] = integrity.group(1)
            continue
        spec = match.group("spec")
        name, separator, version = spec.rpartition("@")
        if not separator or not name or not version:
            raise InventoryError(f"{path}: package key {spec!r} has no name@version form")
        packages.append({"name": name, "version": version})
    return packages


_EXTERNAL_SOURCE = re.compile(
    # option lines that widen the source set, an include of another file whose
    # contents this check would not see, and any URL or VCS reference at all --
    # with or without the "name @ " prefix.
    r"^\s*(?:--(?:find-links|index-url|extra-index-url|editable|requirement)\b|-[fier]\s)"
    r"|(?:^|[\s@=])(?:git|hg|bzr|svn)\+"
    r"|(?:^|[\s@=])(?:https?|ftp|file)://",
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


def _is_license_evidence(path: PurePosixPath) -> bool:
    """Select candidate instruments and provenance, never infer their grant."""
    if path.suffix.lower() in (".py", ".pyi", ".pyc", ".pyo", ".so", ".pyd", ".js", ".mjs", ".cjs", ".ts", ".rs", ".c", ".h", ".cpp"):
        return False
    name = path.name.upper()
    return name.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "UNLICENSE")) or name.endswith((".LICENSE", ".LICENCE", ".ABOUT"))


def _artifact_distributions(artifact_dir: Path, name: str, version: str) -> list[dict[str, Any]]:
    """Read the root and every bundled Python distribution from one wheel."""
    normalized = _NAME_SEPARATORS.sub("_", name.strip().lower())
    candidates = sorted(
        path for path in artifact_dir.glob("*.whl")
        if _NAME_SEPARATORS.sub("_", path.name.partition("-")[0].lower()) == normalized
        and path.name.partition("-")[2].startswith(f"{version}-")
    )
    if not candidates:
        return []
    if len(candidates) != 1:
        raise InventoryError(f"multiple wheels for {name}=={version}; artifact identity is ambiguous")
    artifact = candidates[0]
    with artifact.open("rb") as handle:
        raw_artifact = handle.read(_NATIVE_ARCHIVE_LIMIT + 1)
    if len(raw_artifact) > _NATIVE_ARCHIVE_LIMIT:
        raise InventoryError("wheel exceeds archive evidence limit")
    digest = hashlib.sha256(raw_artifact).hexdigest()
    records = []
    with zipfile.ZipFile(io.BytesIO(raw_artifact)) as archive:
        members = archive.namelist()
        if len(members) != len(set(members)) or any(
            PurePosixPath(member).is_absolute() or ".." in PurePosixPath(member).parts
            for member in members
        ):
            raise InventoryError("wheel has duplicate or unsafe archive paths")
        bundled_archives = []
        for member in members:
            info = archive.getinfo(member)
            if info.is_dir() or not member.lower().endswith((".whl", ".egg", ".zip", ".tar", ".tar.gz", ".tgz", ".crate", ".jar")):
                continue
            if info.file_size > _NATIVE_ARCHIVE_LIMIT:
                raise InventoryError("nested wheel archive exceeds evidence limit")
            bundled_digest = hashlib.sha256()
            with archive.open(member) as handle:
                while chunk := handle.read(65536):
                    bundled_digest.update(chunk)
            bundled_archives.append({"name": member, "sha256": bundled_digest.hexdigest(),
                                     "size": info.file_size, "license_source": "unresolved nested archive scope"})
        unscoped_license_files = []
        for member in members:
            path = PurePosixPath(member)
            if archive.getinfo(member).is_dir() or any(part.endswith(".dist-info") for part in path.parts):
                continue
            if _is_license_evidence(path):
                if archive.getinfo(member).file_size > _NATIVE_TEXT_LIMIT:
                    raise InventoryError("wheel package-body licence exceeds text evidence limit")
                raw = archive.read(member)
                unscoped_license_files.append({"name": member, "sha256": hashlib.sha256(raw).hexdigest(),
                                               "text": raw.decode("utf-8", "replace")})
        metadata_members = [member for member in members if member.endswith(".dist-info/METADATA")]
        roots = [member for member in metadata_members if len(PurePosixPath(member).parts) == 2]
        if len(roots) != 1:
            raise InventoryError("wheel must contain exactly one root distribution metadata record")
        ordered = roots + [member for member in metadata_members if member not in roots]
        distribution_roots = [member.removesuffix("METADATA") for member in ordered]
        for member in members:
            if archive.getinfo(member).is_dir():
                continue
            if ".dist-info/" in member and Path(member).name.upper().startswith(
                ("LICENSE", "LICENCE", "COPYING", "NOTICE", "UNLICENSE")
            ) and not any(member.startswith(root) for root in distribution_roots):
                raise InventoryError("wheel license text belongs to a different distribution")
        for index, metadata_path in enumerate(ordered):
            if any(part.endswith(".dist-info") for part in PurePosixPath(metadata_path).parts[:-2]):
                raise InventoryError("nested metadata is inside another distribution's evidence directory")
            if archive.getinfo(metadata_path).file_size > _NATIVE_TEXT_LIMIT:
                raise InventoryError("wheel metadata exceeds text evidence limit")
            raw_metadata = archive.read(metadata_path)
            metadata = email.message_from_bytes(raw_metadata)
            if any(len(metadata.get_all(field, [])) != 1 for field in ("Name", "Version")):
                raise InventoryError("wheel has missing or duplicate identity fields")
            metadata_name = str(metadata.get("Name") or "").strip()
            metadata_version = str(metadata.get("Version") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", metadata_name) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", metadata_version
            ):
                raise InventoryError("wheel metadata identity is malformed")
            metadata_normalized = _NAME_SEPARATORS.sub("_", metadata_name.lower())
            if index == 0 and (metadata_normalized, metadata_version) != (normalized, version):
                raise InventoryError(f"wheel metadata identity differs from {name}=={version}")
            directory = PurePosixPath(metadata_path).parent.name.removesuffix(".dist-info")
            if _NAME_SEPARATORS.sub("_", directory.lower()) != _NAME_SEPARATORS.sub(
                "_", f"{metadata_name}-{metadata_version}".lower()
            ):
                raise InventoryError("wheel metadata directory disagrees with its identity")
            license_files = []
            declared_files = set()
            for declared in metadata.get_all("License-File", []):
                path = PurePosixPath(declared)
                if path.is_absolute() or ".." in path.parts or not path.parts:
                    raise InventoryError("declared wheel licence path is unsafe")
                targets = [distribution_roots[index] + prefix + declared for prefix in ("", "licenses/")]
                present = [target for target in targets if target in members and not archive.getinfo(target).is_dir()]
                if len(present) != 1:
                    raise InventoryError("declared wheel licence file is missing or ambiguous")
                declared_files.add(present[0])
            for member in members:
                if archive.getinfo(member).is_dir() or not member.startswith(distribution_roots[index]):
                    continue
                if member in declared_files or Path(member).name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "UNLICENSE")):
                    if archive.getinfo(member).file_size > _NATIVE_TEXT_LIMIT:
                        raise InventoryError("wheel licence exceeds text evidence limit")
                    raw = archive.read(member)
                    license_files.append({"name": member, "sha256": hashlib.sha256(raw).hexdigest(),
                                          "text": raw.decode("utf-8", "replace")})
            terms = _metadata_license_terms(metadata)
            source = f"artefact {artifact.name} sha256 {digest}; metadata {metadata_path}"
            if not terms:
                source += "; declares no licence metadata"
            elif not license_files:
                source += "; declaration only: the wheel bundles no licence text"
            record = {"name": metadata_name if index else name, "version": metadata_version,
                      "licenses": terms, "license_source": source, "license_files": license_files,
                      "artifact_sha256": digest, "metadata_sha256": hashlib.sha256(raw_metadata).hexdigest(),
                      "metadata_path": metadata_path}
            if index == 0 and unscoped_license_files:
                record["unscoped_license_files"] = unscoped_license_files
            if index == 0 and bundled_archives:
                record["bundled_archives"] = bundled_archives
            if index:
                record["bundled_in"] = {"name": name, "version": version}
            records.append(record)
    return records


def _artifact_license_terms(
    artifact_dir: Path, name: str, version: str
) -> tuple[list[str], str, list[dict[str, str]]]:
    """Read single-distribution evidence; refuse implicit bundled ownership."""
    records = _artifact_distributions(artifact_dir, name, version)
    if not records:
        return [], f"no wheel for {name}=={version} in {artifact_dir}", []
    if len(records) != 1:
        raise InventoryError("wheel must contain exactly one distribution metadata record")
    record = records[0]
    files = [{**entry, "name": Path(entry["name"]).name} for entry in record["license_files"]]
    return record["licenses"], record["license_source"], files


# ponytail: bounded in-memory archive reads; oversized artifacts fail closed.
# Stream to a verified temporary file if a future locked artifact exceeds this cap.
_NATIVE_ARCHIVE_LIMIT = 256 * 1024 * 1024
_NATIVE_TEXT_LIMIT = 4 * 1024 * 1024


def _native_artifact_spec(ecosystem: str, package: dict[str, Any]) -> tuple[str, str, str]:
    """Return a canonical registry URL and the lock's strong digest, never a custom source."""
    name, version = package["name"], package["version"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]*", version):
        raise InventoryError(f"{ecosystem}:{name}: unsupported version")
    if ecosystem == "cargo":
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise InventoryError("unsafe crate name")
        if package.get("source") != "registry+https://github.com/rust-lang/crates.io-index":
            raise InventoryError(f"cargo:{name}: registry source is not supported")
        checksum = package.get("checksum", "")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise InventoryError(f"cargo:{name}: missing SHA256 lock checksum")
        return f"https://static.crates.io/crates/{name}/{name}-{version}.crate", "sha256", checksum
    if not re.fullmatch(r"(?:@[a-z0-9._-]+/)?[a-z0-9][a-z0-9._-]*", name):
        raise InventoryError("unsafe npm package name")
    integrity = package.get("integrity", "")
    if not isinstance(integrity, str) or not integrity.startswith("sha512-"):
        raise InventoryError(f"npm:{name}: missing SHA512 lock integrity")
    try:
        digest = base64.b64decode(integrity[7:], validate=True)
    except (ValueError, binascii.Error) as error:
        raise InventoryError(f"npm:{name}: malformed integrity") from error
    if len(digest) != 64:
        raise InventoryError(f"npm:{name}: malformed SHA512 digest")
    url = f"https://registry.npmjs.org/{name}/-/{name.rsplit('/', 1)[-1]}-{version}.tgz"
    if package.get("resolved", url) != url:
        raise InventoryError(f"npm:{name}: archive URL is not the canonical registry source")
    return url, "sha512", digest.hex()


class _NoRegistryRedirect(urllib.request.HTTPRedirectHandler):
    """Registry redirects are not an authorization to fetch a different origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _native_license_terms(
    ecosystem: str, package: dict[str, Any], artifact_dir: Path | None, download: bool
) -> tuple[list[str], str, list[dict[str, str]]]:
    """Read exact locked Cargo/npm archive bytes without extraction or package execution."""
    url, algorithm, expected = _native_artifact_spec(ecosystem, package)
    if artifact_dir is None:
        return [], "native artifact directory absent", []
    suffix = ".crate" if ecosystem == "cargo" else ".tgz"
    artifact = artifact_dir / (hashlib.sha256(url.encode()).hexdigest() + suffix)
    if artifact.is_symlink():
        raise InventoryError("native artifact cache entry is a symbolic link")
    if artifact.exists():
        with artifact.open("rb") as handle:
            raw = handle.read(_NATIVE_ARCHIVE_LIMIT + 1)
    elif download:
        opener = urllib.request.build_opener(_NoRegistryRedirect())
        try:
            with opener.open(url, timeout=60) as response:
                raw = response.read(_NATIVE_ARCHIVE_LIMIT + 1)
        except urllib.error.HTTPError as error:
            try:
                error.close()
            except Exception:
                pass  # Cleanup cannot replace the registry failure.
            raise InventoryError(f"registry download failed with HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise InventoryError("registry download failed") from error
    else:
        return [], f"locked native artifact absent: {artifact.name}", []
    if len(raw) > _NATIVE_ARCHIVE_LIMIT:
        raise InventoryError("native artifact exceeds the 256 MiB evidence limit")
    digest = hashlib.new(algorithm, raw).hexdigest()
    if digest != expected:
        raise InventoryError(f"{ecosystem}:{package['name']}: artifact digest differs from lock")
    metadata_name = "Cargo.toml" if ecosystem == "cargo" else "package.json"
    prefix = f"{package['name']}-{package['version']}" if ecosystem == "cargo" else None
    files: dict[str, bytes] = {}
    expanded = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r|gz") as archive:
        for index, member in enumerate(archive):
            if index >= 100000:
                raise InventoryError("native archive exceeds the 100000-entry evidence limit")
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise InventoryError("native archive contains an unsafe path")
            # npm strips one directory layer; DefinitelyTyped tarballs use a
            # different root name. Identity is bound by metadata and lock digest.
            if prefix is None:
                prefix = path.parts[0]
            if path.parts[0] != prefix:
                raise InventoryError("native archive contains more than one package root")
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise InventoryError("native archive contains a link or special entry")
            expanded += member.size
            if expanded > 2 * 1024 * 1024 * 1024:
                raise InventoryError("native archive exceeds the 2 GiB expanded evidence limit")
            selected = str(path) == f"{prefix}/{metadata_name}" or _is_license_evidence(path)
            if not member.isfile() or not selected:
                continue
            if str(path) in files or member.size > _NATIVE_TEXT_LIMIT:
                raise InventoryError("native archive has duplicate or oversized evidence")
            handle = archive.extractfile(member)
            if handle is None:
                raise InventoryError("native archive evidence cannot be read")
            with handle:
                files[str(path)] = handle.read(_NATIVE_TEXT_LIMIT + 1)
    metadata_raw = files.pop(f"{prefix}/{metadata_name}", None)
    if metadata_raw is None:
        raise InventoryError("native archive contains no package metadata")
    metadata = (tomllib.loads(metadata_raw.decode())["package"] if ecosystem == "cargo"
                else json.loads(metadata_raw))
    if not isinstance(metadata, dict):
        raise InventoryError("native artifact metadata is not an object")
    if (metadata.get("name"), metadata.get("version")) != (package["name"], package["version"]):
        raise InventoryError("native artifact identity differs from lock")
    filename = metadata.get("license-file") if ecosystem == "cargo" else None
    if filename is not None:
        if not isinstance(filename, str) or PurePosixPath(filename).is_absolute() or ".." in PurePosixPath(filename).parts:
            raise InventoryError("native artifact declares an unsafe license file")
        target = str(PurePosixPath(prefix) / filename)
        if target not in files:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r|gz") as archive:
                for member in archive:
                    if str(PurePosixPath(member.name)) != target:
                        continue
                    if target in files or not member.isfile() or member.size > _NATIVE_TEXT_LIMIT:
                        raise InventoryError("declared license file is duplicated or not bounded regular text")
                    handle = archive.extractfile(member)
                    if handle is None:
                        raise InventoryError("declared license file cannot be read")
                    with handle:
                        files[target] = handle.read(_NATIVE_TEXT_LIMIT + 1)
            if target not in files:
                raise InventoryError("declared license file is absent from native artifact")
    declaration = metadata.get("license")
    terms = [declaration] if isinstance(declaration, str) and declaration.strip() else []
    license_files = [{"name": name, "sha256": hashlib.sha256(data).hexdigest(),
                      "text": data.decode("utf-8", "replace")} for name, data in sorted(files.items())]
    if download and not artifact.exists():
        artifact_dir.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also refuses a cache entry replaced by a concurrent writer.
        with artifact.open("xb") as handle:
            handle.write(raw)
    return terms, f"{url} ({algorithm} {digest})", license_files


def _local_cargo_license_terms(
    root: Path, package: dict[str, Any], commit: str, provenance: list[dict[str, Any]]
) -> tuple[list[str], str, list[dict[str, str]]]:
    """Bind workspace license declarations and text to committed source bytes."""
    workspace = root / "rust" / "Cargo.toml"
    if not workspace.is_file():
        return [], "workspace manifest absent", []
    data, record = _read_locked_source(root, workspace, commit)
    provenance.append(record)
    members = tomllib.loads(data.decode()).get("workspace", {}).get("members", [])
    for member in members:
        manifest = (workspace.parent / member / "Cargo.toml").resolve()
        if not manifest.is_relative_to(root) or not manifest.is_file():
            raise InventoryError("workspace member manifest is absent or outside repository")
        data, record = _read_locked_source(root, manifest, commit)
        metadata = tomllib.loads(data.decode()).get("package", {})
        if (metadata.get("name"), metadata.get("version")) != (package["name"], package["version"]):
            continue
        provenance.append(record)
        declaration, filename = metadata.get("license"), metadata.get("license-file")
        if not isinstance(declaration, str) or not isinstance(filename, str):
            return [], "workspace license declaration/file absent", []
        license_path = (manifest.parent / filename).resolve()
        if not license_path.is_relative_to(root):
            raise InventoryError("workspace license file is outside repository")
        raw, record = _read_locked_source(root, license_path, commit)
        provenance.append(record)
        return [declaration], f"committed workspace {manifest.relative_to(root)}", [
            {"name": str(license_path.relative_to(root)), "sha256": hashlib.sha256(raw).hexdigest(),
             "text": raw.decode("utf-8", "replace")}
        ]
    return [], "local crate is not a declared workspace member", []


def _local_project_license_terms(root: Path, package: dict[str, Any], commit: str,
                                 provenance: list[dict[str, Any]]) -> tuple[list[str], str, list[dict[str, str]]]:
    """Read committed root-project evidence before its distribution can exist."""
    data, record = _read_locked_source(root, root / "pyproject.toml", commit)
    provenance.append(record)
    project = tomllib.loads(data.decode()).get("project", {})
    if (project.get("name"), project.get("version")) != (package["name"], package["version"]):
        raise InventoryError("local project identity disagrees with the locked package")
    declaration, patterns = project.get("license"), project.get("license-files")
    if not isinstance(declaration, str) or not isinstance(patterns, list) or not patterns:
        return [], "local project licence declaration/files absent", []
    files = []
    for pattern in patterns:
        if not isinstance(pattern, str) or PurePosixPath(pattern).is_absolute() or ".." in PurePosixPath(pattern).parts:
            raise InventoryError("local project licence pattern is outside repository")
        matches = sorted(root.glob(pattern))
        if not matches:
            return [], "local project licence pattern matches no files", []
        for path in matches:
            if not path.resolve().is_relative_to(root) or not path.is_file():
                raise InventoryError("local project licence file is outside repository or not a file")
            raw, record = _read_locked_source(root, path, commit)
            provenance.append(record)
            files.append({"name": str(path.relative_to(root)), "sha256": hashlib.sha256(raw).hexdigest(),
                          "text": raw.decode("utf-8", "replace")})
    return [declaration], "committed prebuild project source (not wheel evidence)", files


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


def _installed_license_terms(name: str, version: str) -> tuple[list[str], str, list[dict[str, str]]]:
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
        return [], "absent from this environment", []
    metadata = distribution.metadata
    if str(metadata.get("Version") or "") != version:
        return [], f"environment holds {metadata.get('Version')!r}, not the locked version", []
    terms = _metadata_license_terms(metadata)
    files = []
    root = Path(distribution.locate_file("")).resolve()
    try:
        for member in distribution.files or []:
            if not member.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "UNLICENSE")):
                continue
            path = Path(distribution.locate_file(member)).resolve()
            if not path.is_relative_to(root):
                return terms, "license file outside installed distribution root", []
            raw = path.read_bytes()
            files.append({"name": member.name, "sha256": hashlib.sha256(raw).hexdigest(),
                          "text": raw.decode("utf-8", errors="replace")})
    except OSError:
        return terms, "unreadable installed license file", []
    return terms, "installed distribution metadata", files


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
    repository_root: Path, resolve_licenses: bool = False, artifact_dir: Path | None = None,
    download_native_artifacts: bool = False, prebuild_local_project: bool = False,
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
                        if (known.get("integrity") and package.get("integrity")
                                and known["integrity"] != package["integrity"]):
                            raise InventoryError(f"npm:{package['name']}: lockfiles disagree on integrity")
                        known.update({key: package[key] for key in ("integrity",) if key in package})
                        known["sources"].append(pnpm_provenance["path"])
                        continue
                    package["sources"] = [pnpm_provenance["path"]]
                    index[key] = package
                    packages.append(package)
        for package in packages:
            package["purl"] = f"{purl_prefix}{package['name']}@{package['version']}"
        entry["packages"] = sorted(packages, key=lambda package: (package["name"], package["version"]))
        ecosystems.append(entry)
    if resolve_licenses:
        if download_native_artifacts and any(
            not record.get("matches_commit") for entry in ecosystems
            for record in entry.get("provenance", [])
        ):
            raise InventoryError("uncommitted lockfile bytes cannot authorize native downloads")
        for entry in ecosystems:
            for package in list(entry["packages"]):
                if entry["ecosystem"] == "python":
                    if prebuild_local_project and package.get("source") in ({"editable": "."}, {"virtual": "."}):
                        terms, source, license_files = _local_project_license_terms(
                            repository_root, package, commit, entry["provenance"]
                        )
                        package["license_evidence"] = "prebuild-source"
                    elif artifact_dir is not None:
                        records = _artifact_distributions(artifact_dir, package["name"], package["version"])
                        if records:
                            package.update(records[0])
                            terms, source, license_files = (package[key] for key in
                                                           ("licenses", "license_source", "license_files"))
                            for bundled in records[1:]:
                                bundled["purl"] = f"pkg:pypi/{bundled['name']}@{bundled['version']}"
                                bundled["sources"] = list(package["sources"])
                                entry["packages"].append(bundled)
                        else:
                            terms, source, license_files = [], f"no wheel for {package['name']}=={package['version']}", []
                    else:
                        terms, source, license_files = _installed_license_terms(package["name"], package["version"])
                else:
                    try:
                        if entry["ecosystem"] == "cargo" and "source" not in package:
                            terms, source, license_files = _local_cargo_license_terms(
                                repository_root, package, commit, entry["provenance"]
                            )
                        else:
                            terms, source, license_files = _native_license_terms(
                                entry["ecosystem"], package, artifact_dir, download_native_artifacts
                            )
                    except (InventoryError, OSError, ValueError, KeyError, EOFError, tarfile.TarError) as error:
                        terms, source, license_files = [], str(error), []
                package["licenses"] = terms
                package["license_files"] = license_files
                package["license_source"] = source if terms else f"unresolved: {source}"
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
        help="attach licence terms from staged archives or installed Python metadata",
    )
    parser.add_argument(
        "--check-sources-only", action="store_true",
        help="report requirements that reach outside the hash-pinned wheel set, and stop",
    )
    parser.add_argument(
        "--artifact-dir",
        help="read licences from downloaded distribution artefacts here instead of installed metadata",
    )
    parser.add_argument(
        "--download-native-artifacts", action="store_true",
        help="fetch hash-pinned canonical Cargo/npm archives without installing or running code",
    )
    parser.add_argument("--prebuild-local-project", action="store_true",
                        help="use committed root-project source only for preinstall evidence")
    arguments = parser.parse_args(argv)
    if arguments.download_native_artifacts and not arguments.artifact_dir:
        parser.error("--download-native-artifacts requires --artifact-dir")
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
            resolve_licenses=arguments.resolve_licenses or bool(arguments.artifact_dir) or arguments.prebuild_local_project,
            artifact_dir=Path(arguments.artifact_dir).resolve() if arguments.artifact_dir else None,
            download_native_artifacts=arguments.download_native_artifacts,
            prebuild_local_project=arguments.prebuild_local_project,
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
