"""The non-shipped dependency classes must still be enumerated and bound to a commit.

A release SBOM built from an installed environment cannot see the `dev`, `fuzz`
and `native-build` groups, the Rust workspace or the npm tree. Scoping the SBOM
down does not discharge the licence policy, so those classes are emitted as a
separate inventory carrying the same `source_sha`, and an unprovable scope fails
rather than disappearing.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from scripts.ci.dependency_inventory import (  # noqa: E402
    InventoryError,
    _artifact_license_terms,
    external_source_findings,
    _pnpm_packages,
    build_inventory,
    main,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_inventory_covers_every_lockfile_resolved_scope(tmp_path) -> None:
    output = tmp_path / "dependency-inventory.json"

    # Source enumeration succeeds; artifact adjudication is a separate gate.
    assert main(["--repository-root", str(REPOSITORY_ROOT), "--output", str(output)]) == 0

    inventory = json.loads(output.read_text(encoding="utf-8"))
    by_ecosystem = {entry["ecosystem"]: entry for entry in inventory["ecosystems"]}
    assert set(by_ecosystem) == {"python", "cargo", "npm"}
    for ecosystem, entry in by_ecosystem.items():
        assert entry["packages"], f"{ecosystem} inventory is empty"
        assert all(package["purl"].startswith("pkg:") for package in entry["packages"])
    assert len(inventory["source_sha"]) == 40
    # The dev-group and Rust members the environment SBOM cannot see.
    python_names = {package["name"] for package in by_ecosystem["python"]["packages"]}
    cargo_names = {package["name"] for package in by_ecosystem["cargo"]["packages"]}
    assert {"pytest", "hypothesis"} <= python_names
    assert "contextual-token-packer" in cargo_names
    # Both npm lockfiles are read: package-lock.json alone omits the pnpm
    # workspace tree, which a single-lockfile reading silently loses.
    npm_names = {package["name"] for package in by_ecosystem["npm"]["packages"]}
    assert {"opencode-ai", "react"} <= npm_names
    assert "pnpm-lock.yaml" in by_ecosystem["npm"]["lockfile"]


def test_absent_lockfile_is_reported_as_unprovable(tmp_path) -> None:
    (tmp_path / "rust").mkdir()
    (tmp_path / "uv.lock").write_text('[[package]]\nname = "only_library"\nversion = "1.0"\n', encoding="utf-8")

    inventory = build_inventory(tmp_path)
    errors = {entry["ecosystem"]: entry.get("error") for entry in inventory["ecosystems"]}

    assert errors["cargo"] and errors["npm"]
    assert main(["--repository-root", str(tmp_path), "--output", str(tmp_path / "out.json")]) == 1


def test_security_workflow_publishes_the_inventory_with_the_sbom() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")

    assert "scripts.ci.dependency_inventory" in workflow
    assert workflow.index("scripts.ci.dependency_inventory") < workflow.index("Upload CycloneDX SBOM")
    upload = workflow[workflow.index("Upload CycloneDX SBOM") : workflow.index("Run CodeQL analysis")]
    assert "dependency-inventory.json" in upload


# --- negative cases: silence must not read as a clean scope ---


def _repository(tmp_path: Path, *, uv: str | None = None, npm: dict | None = None) -> Path:
    """A committed miniature repository, so provenance can be checked."""
    (tmp_path / "rust").mkdir()
    (tmp_path / "uv.lock").write_text(
        uv if uv is not None else '[[package]]\nname = "only_library"\nversion = "1.0"\n', encoding="utf-8")
    (tmp_path / "rust" / "Cargo.lock").write_text(
        '[[package]]\nname = "only_crate"\nversion = "0.1.0"\n', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text(
        json.dumps(npm if npm is not None else {"packages": {"node_modules/one": {"version": "1.0.0"}}}),
        encoding="utf-8")
    for command in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t",
                                                    "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(tmp_path), *command], check=True, capture_output=True)
    return tmp_path


def test_malformed_lock_entry_is_refused_not_skipped(tmp_path) -> None:
    repository = _repository(tmp_path, uv='[[package]]\nname = "no_version_library"\n')

    assert main(["--repository-root", str(repository), "--output", str(tmp_path / "out.json")]) == 1


def test_empty_resolved_set_is_refused(tmp_path) -> None:
    repository = _repository(tmp_path, uv="version = 1\n")

    assert main(["--repository-root", str(repository), "--output", str(tmp_path / "out.json")]) == 1


def test_nested_node_modules_path_keeps_the_real_package_name(tmp_path) -> None:
    repository = _repository(
        tmp_path, npm={"packages": {"node_modules/outer/node_modules/inner": {"version": "2.0.0"}}})

    inventory = build_inventory(repository)
    npm = next(entry for entry in inventory["ecosystems"] if entry["ecosystem"] == "npm")

    assert [package["name"] for package in npm["packages"]] == ["inner"]


def test_modified_lockfile_bytes_are_refused(tmp_path) -> None:
    """An inventory of uncommitted bytes cannot be bound to any released commit."""
    repository = _repository(tmp_path)
    (repository / "uv.lock").write_text(
        '[[package]]\nname = "only_library"\nversion = "9.9"\n', encoding="utf-8")

    inventory = build_inventory(repository)
    python = next(entry for entry in inventory["ecosystems"] if entry["ecosystem"] == "python")

    assert python["provenance"][0]["matches_commit"] is False
    assert main(["--repository-root", str(repository), "--output", str(tmp_path / "out.json")]) == 1


def test_unresolvable_source_commit_is_refused(tmp_path) -> None:
    (tmp_path / "rust").mkdir()
    (tmp_path / "uv.lock").write_text('[[package]]\nname = "l"\nversion = "1"\n', encoding="utf-8")
    (tmp_path / "rust" / "Cargo.lock").write_text('[[package]]\nname = "c"\nversion = "1"\n', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text('{"packages":{"node_modules/one":{"version":"1"}}}',
                                                encoding="utf-8")

    assert main(["--repository-root", str(tmp_path), "--output", str(tmp_path / "out.json")]) == 1


def test_double_quoted_pnpm_keys_are_parsed(tmp_path) -> None:
    lock = tmp_path / "pnpm-lock.yaml"
    lock.write_text(
        "lockfileVersion: '9.0'\n\npackages:\n\n"
        '  "@scope/quoted@1.2.3":\n    resolution: {integrity: sha512-x}\n'
        "  'single@4.5.6':\n    resolution: {integrity: sha512-y}\n",
        encoding="utf-8",
    )

    packages = _pnpm_packages(lock, lock.read_bytes())

    assert {(p["name"], p["version"]) for p in packages} == {("@scope/quoted", "1.2.3"), ("single", "4.5.6")}


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("lockfileVersion: 999\n\npackages:\n\n  'x@1.0.0':\n", id="unsupported_version"),
        pytest.param("packages:\n\n  'x@1.0.0':\n", id="no_version_declared"),
        pytest.param("lockfileVersion: '6.0'\n\npackages:\n\n  /x@1.0.0(peer@2.0.0):\n", id="v6_peer_suffix"),
        pytest.param("this is not: [a, lockfile\n", id="malformed"),
    ],
)
def test_unsupported_or_malformed_pnpm_lock_fails_closed(tmp_path, content) -> None:
    lock = tmp_path / "pnpm-lock.yaml"
    lock.write_text(content, encoding="utf-8")

    with pytest.raises(InventoryError):
        _pnpm_packages(lock, lock.read_bytes())


def test_python_scope_includes_the_pinned_ci_and_fuzz_toolchains() -> None:
    """uv.lock alone is not the declared Python scope: the CI locks install too."""
    inventory = build_inventory(REPOSITORY_ROOT)
    python = next(entry for entry in inventory["ecosystems"] if entry["ecosystem"] == "python")
    names = {package["name"] for package in python["packages"]}

    for source in ("uv.lock", "requirements.lock", "requirements-security-ci.txt",
                   "fuzz/requirements-property.txt"):
        assert source in python["lockfile"]
    assert "pip-audit" in names  # retained security CI toolchain
    assert not {"cyclonedx-bom", "chardet"} & names
    assert len(python["provenance"]) == len(python["lockfile"].split(", "))


def _wheel(directory: Path, name: str, version: str, metadata_lines: list[str]) -> Path:
    """A minimal wheel: the licence evidence lives in its own dist-info METADATA."""
    path = directory / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{name}-{version}.dist-info/METADATA",
            "\n".join([f"Name: {name}", f"Version: {version}", *metadata_lines]) + "\n",
        )
    return path


def test_licences_are_read_from_the_artifact_not_from_an_install(tmp_path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    wheel = _wheel(artifacts, "example_library", "1.2.3", ["License-Expression: 0BSD"])

    terms, source, license_files = _artifact_license_terms(artifacts, "Example.Library", "1.2.3")

    assert terms == ["0BSD"]
    assert license_files == []
    # The evidence is tied to the exact bytes, not to a registry's claim.
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() in source


def test_declaration_without_bundled_text_is_recorded_as_such(tmp_path) -> None:
    """A METADATA line is the publisher's statement, not the licence instrument."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _wheel(artifacts, "declared_only_library", "1.0", ["License-Expression: MIT"])

    terms, source, _ = _artifact_license_terms(artifacts, "declared_only_library", "1.0")

    assert terms == ["MIT"]
    assert "declaration only" in source


def test_sdist_is_not_read_for_licences(tmp_path) -> None:
    """Reading an sdist usefully means running its build backend, so it is skipped."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "sdist_only_library-1.0.tar.gz").write_bytes(b"not read")

    terms, source, _ = _artifact_license_terms(artifacts, "sdist_only_library", "1.0")

    assert terms == []
    assert "no wheel" in source


def test_absent_or_silent_artifact_resolves_to_nothing(tmp_path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _wheel(artifacts, "silent_library", "1.0", [])

    assert _artifact_license_terms(artifacts, "silent_library", "1.0")[0] == []
    assert _artifact_license_terms(artifacts, "missing_library", "1.0")[0] == []
    assert "no wheel" in _artifact_license_terms(artifacts, "missing_library", "1.0")[1]


def test_security_workflow_adjudicates_before_installing_and_installs_what_it_read() -> None:
    """Collection must precede installation, and installation must not re-download."""
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    sources = workflow.index("--check-sources-only")
    download = workflow.index("collect_python_license_artifacts.sh")
    collect = workflow.index("--artifact-dir license-artifacts")
    adjudicate = workflow.index("scripts.ci.release_license_gate")
    install = workflow.index("pip install --require-hashes --no-index")

    # Refuse external sources before fetching, then gather, then judge, then
    # install: each step's evidence has to exist before the next one acts.
    assert sources < download < collect < adjudicate < install
    collector = (REPOSITORY_ROOT / "scripts/ci/collect_python_license_artifacts.sh").read_text()
    assert "--only-binary=:all:" in collector, "sdist build backends must not run"
    install_block = workflow[install:install + 200]
    assert "--find-links license-artifacts" in install_block
    assert workflow.count("collect_python_license_artifacts.sh") == 1


def test_external_source_requirements_are_refused(tmp_path) -> None:
    """A direct URL or VCS requirement is fetched and built despite --no-index."""
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "normal-library==1.0 \\\n    --hash=sha256:aa\n"
        "vcs-library @ git+https://example.invalid/pkg.git@deadbeef\n"
        "--find-links https://example.invalid/wheels\n",
        encoding="utf-8",
    )

    findings = external_source_findings(lock, lock.read_bytes())

    assert len(findings) == 2
    assert any("git+https" in finding for finding in findings)
    assert any("--find-links" in finding for finding in findings)


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("https://example.invalid/pkg-1.0-py3-none-any.whl", id="bare_wheel_url"),
        pytest.param("git+https://example.invalid/pkg.git@deadbeef", id="bare_vcs_url"),
        pytest.param("-r other.lock", id="include_of_another_file"),
        pytest.param("-e .", id="editable"),
    ],
)
def test_every_external_source_shape_is_refused(tmp_path, line) -> None:
    """A URL, a VCS reference or an include reaches outside the pinned wheel set."""
    lock = tmp_path / "requirements.lock"
    lock.write_text(f"{line}\n", encoding="utf-8")

    assert external_source_findings(lock, lock.read_bytes())


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("normal-library==1.0 \\", id="pinned_requirement"),
        pytest.param("    --hash=sha256:aa", id="hash_line"),
        pytest.param("# via https://example.invalid/docs", id="comment_mentioning_a_url"),
    ],
)
def test_ordinary_lock_lines_are_not_refused(tmp_path, line) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text(f"{line}\n", encoding="utf-8")

    assert external_source_findings(lock, lock.read_bytes()) == []


def _native_archive(directory, ecosystem, name, version, license_text, *, identity=None,
                    extra=None, declaration="MIT", license_filename="LICENSE", archive_prefix=None):
    """Fabricate a registry archive with inert hooks and an exact locked digest."""
    import base64
    import io
    import tarfile

    from scripts.ci.dependency_inventory import _native_artifact_spec

    prefix = archive_prefix or (f"{name}-{version}" if ecosystem == "cargo" else "package")
    identity = identity or (name, version)
    metadata = (
        f'[package]\nname = "{identity[0]}"\nversion = "{identity[1]}"\nlicense = "{declaration}"\n'
        if ecosystem == "cargo" else json.dumps({"name": identity[0], "version": identity[1],
                                               "license": declaration,
                                               "scripts": {"install": "exit 99"}})
    )
    if ecosystem == "cargo" and license_filename != "LICENSE":
        metadata += f'license-file = "{license_filename}"\n'
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        files = {f"{prefix}/{'Cargo.toml' if ecosystem == 'cargo' else 'package.json'}": metadata,
                 f"{prefix}/install.sh": "exit 99"}
        if license_text is not None:
            files[f"{prefix}/{license_filename}"] = license_text
        files.update(extra or {})
        for path, text in files.items():
            raw = text.encode()
            member = tarfile.TarInfo(path)
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    raw = stream.getvalue()
    package = {"name": name, "version": version}
    if ecosystem == "cargo":
        package.update(source="registry+https://github.com/rust-lang/crates.io-index",
                       checksum=hashlib.sha256(raw).hexdigest())
    else:
        package["integrity"] = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
    url, _, _ = _native_artifact_spec(ecosystem, package)
    suffix = ".crate" if ecosystem == "cargo" else ".tgz"
    path = directory / (hashlib.sha256(url.encode()).hexdigest() + suffix)
    path.write_bytes(raw)
    return package, path


@pytest.mark.parametrize("ecosystem", ["cargo", "npm"])
@pytest.mark.parametrize("failure", [None, "identity", "digest", "missing_text", "copyleft", "traversal"])
def test_native_artifact_license_evidence_is_lock_bound_and_fails_closed(tmp_path, ecosystem, failure):
    from scripts.ci.dependency_inventory import _native_license_terms
    from scripts.ci.release_license_gate import classify_inventory_licenses

    text = "MIT License. Permission is hereby granted, free of charge, to any person."
    if failure == "missing_text":
        text = None
    if failure == "copyleft":
        text += " This library is licensed under the GNU General Public License."
    package, archive = _native_archive(
        tmp_path, ecosystem, "example", "1.2.3", text,
        identity=("another", "1.2.3") if failure == "identity" else None,
        extra={"../LICENSE": text} if failure == "traversal" else None,
    )
    if failure == "digest":
        archive.write_bytes(archive.read_bytes() + b"changed")
    if failure in {"identity", "digest", "traversal"}:
        with pytest.raises(InventoryError):
            _native_license_terms(ecosystem, package, tmp_path, False)
        return
    terms, source, files = _native_license_terms(ecosystem, package, tmp_path, False)
    package.update(licenses=terms, license_files=files, license_source=source)
    groups = classify_inventory_licenses({"ecosystems": [{"ecosystem": ecosystem, "packages": [package]}]})
    if failure:
        assert not groups["permitted"]
        assert groups["undecidable"] or groups["copyleft"]
    else:
        assert len(groups["permitted"]) == 1
        assert files[0]["sha256"] == hashlib.sha256(text.encode()).hexdigest()
        assert hashlib.new("sha256" if ecosystem == "cargo" else "sha512", archive.read_bytes()).hexdigest() in source


def test_verified_native_archive_without_declaration_is_distinct_from_missing_archive(tmp_path):
    from scripts.ci.dependency_inventory import _native_license_terms

    package, _ = _native_archive(tmp_path, "npm", "example", "1.2.3", None, declaration=None)
    terms, source, files = _native_license_terms("npm", package, tmp_path, False)
    assert terms == [] and files == []
    assert "declares no supported licence metadata" in source
    missing = _native_license_terms("npm", package, tmp_path / "absent", False)
    assert "locked native artifact absent" in missing[1]
    assert "declares no supported licence metadata" not in missing[1]


def test_native_collection_covers_both_npm_locks_and_local_workspace(tmp_path):
    """All native entries get evidence, including dev/optional and local members."""
    from scripts.ci.release_license_gate import classify_inventory_licenses

    root = _repository(tmp_path)
    artifacts = root / "artifacts"
    artifacts.mkdir()
    text = "MIT License. Permission is hereby granted, free of charge, to any person."
    crate, _ = _native_archive(artifacts, "cargo", "registry_crate", "1.2.3", text)
    npm, _ = _native_archive(artifacts, "npm", "optional", "1.2.3", text)
    pnpm, _ = _native_archive(artifacts, "npm", "@scope/dev", "1.2.3", text)
    (root / "rust/Cargo.lock").write_text(
        f'[[package]]\nname = "registry_crate"\nversion = "1.2.3"\nsource = "{crate["source"]}"\n'
        f'checksum = "{crate["checksum"]}"\n\n[[package]]\nname = "local"\nversion = "1.0"\n')
    (root / "rust/Cargo.toml").write_text('[workspace]\nmembers = ["local"]\n')
    (root / "rust/local").mkdir()
    (root / "rust/local/Cargo.toml").write_text(
        '[package]\nname = "local"\nversion = "1.0"\nlicense = "MIT"\nlicense-file = "../../LICENSE"\n')
    (root / "LICENSE").write_text(text)
    (root / "package-lock.json").write_text(json.dumps({"packages": {"node_modules/optional": {
        "version": "1.2.3", "integrity": npm["integrity"], "optional": True, "dev": True}}}))
    (root / "pnpm-lock.yaml").write_text(
        f"lockfileVersion: '9.0'\npackages:\n  '@scope/dev@1.2.3':\n    resolution: {{integrity: {pnpm['integrity']}}}\n")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "native evidence"], check=True)
    inventory = build_inventory(root, resolve_licenses=True, artifact_dir=artifacts)
    native = [entry for entry in inventory["ecosystems"] if entry["ecosystem"] != "python"]
    assert sum(len(entry["packages"]) for entry in native) == 4
    assert all(record["matches_commit"] for entry in native for record in entry["provenance"])
    groups = classify_inventory_licenses({"ecosystems": native})
    assert len(groups["permitted"]) == 4
    assert not groups["undecidable"] and not groups["copyleft"]
    (root / "LICENSE").write_text("uncommitted replacement")
    changed = build_inventory(root, resolve_licenses=True, artifact_dir=artifacts)
    cargo = next(entry for entry in changed["ecosystems"] if entry["ecosystem"] == "cargo")
    assert any(not record["matches_commit"] for record in cargo["provenance"])


def test_native_registry_source_cannot_redirect_or_execute_package_hooks(tmp_path, monkeypatch):
    import io
    import urllib.error
    import urllib.request

    from scripts.ci.dependency_inventory import _native_license_terms, _NoRegistryRedirect

    package, archive = _native_archive(tmp_path, "npm", "example", "1.2.3", "MIT License")
    raw = archive.read_bytes()
    archive.unlink()
    calls = []

    class Registry:
        def open(self, url, timeout):
            calls.append(url)
            return io.BytesIO(raw)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Registry())
    _native_license_terms("npm", package, tmp_path, True)
    assert calls == ["https://registry.npmjs.org/example/-/example-1.2.3.tgz"]
    assert archive.read_bytes() == raw
    package["resolved"] = "https://untrusted.invalid/example.tgz"
    with pytest.raises(InventoryError, match="canonical"):
        _native_license_terms("npm", package, tmp_path, True)
    assert len(calls) == 1
    assert _NoRegistryRedirect().redirect_request(None, None, 302, "", {}, "https://untrusted.invalid") is None

    error = urllib.error.HTTPError(calls[0], 302, "redirect", {}, io.BytesIO(b"private"))
    class RedirectingRegistry:
        def open(self, *args, **kwargs):
            raise error
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: RedirectingRegistry())
    archive.unlink()
    package.pop("resolved")
    with pytest.raises(InventoryError, match="HTTP 302"):
        _native_license_terms("npm", package, tmp_path, True)
    assert error.fp.closed


def test_native_archive_refuses_links_duplicates_and_evidence_limits(tmp_path, monkeypatch):
    import io
    import tarfile

    import scripts.ci.dependency_inventory as inventory

    package, path = _native_archive(tmp_path, "cargo", "example", "1.2.3", "MIT License")
    original = path.read_bytes()
    for failure in ("link", "duplicate"):
        stream = io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(original), mode="r:gz") as source:
            with tarfile.open(fileobj=stream, mode="w:gz") as target:
                for member in source:
                    target.addfile(member, source.extractfile(member))
                extra = tarfile.TarInfo("example-1.2.3/LICENSE" if failure == "duplicate"
                                        else "example-1.2.3/link")
                if failure == "link":
                    extra.type = tarfile.SYMTYPE
                    extra.linkname = "../../LICENSE"
                target.addfile(extra)
        raw = stream.getvalue()
        package["checksum"] = hashlib.sha256(raw).hexdigest()
        path.write_bytes(raw)
        with pytest.raises(InventoryError, match="link|duplicate"):
            inventory._native_license_terms("cargo", package, tmp_path, False)
    path.write_bytes(original)
    package["checksum"] = hashlib.sha256(original).hexdigest()
    monkeypatch.setattr(inventory, "_NATIVE_ARCHIVE_LIMIT", len(original) - 1)
    with pytest.raises(InventoryError, match="evidence limit"):
        inventory._native_license_terms("cargo", package, tmp_path, False)


def test_dirty_locks_cannot_authorize_native_downloads(tmp_path, monkeypatch):
    import scripts.ci.dependency_inventory as inventory

    root = _repository(tmp_path)
    (root / "rust/Cargo.lock").write_text('[[package]]\nname = "changed"\nversion = "1"\n')
    monkeypatch.setattr(inventory, "_native_license_terms",
                        lambda *args: pytest.fail("dirty locks reached artifact collection"))
    with pytest.raises(InventoryError, match="uncommitted"):
        build_inventory(root, True, tmp_path / "artifacts", download_native_artifacts=True)


def test_conflicting_npm_lock_integrity_is_not_silently_deduplicated(tmp_path):
    root = _repository(tmp_path, npm={"packages": {"node_modules/one": {
        "version": "1.0.0", "integrity": "sha512-first"}}})
    (root / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\npackages:\n  one@1.0.0:\n    resolution: {integrity: sha512-second}\n")
    with pytest.raises(InventoryError, match="disagree"):
        build_inventory(root)


def test_explicit_cargo_license_file_is_read_without_filename_guessing(tmp_path):
    from scripts.ci.dependency_inventory import _native_license_terms

    text = "MIT License. Permission is hereby granted, free of charge, to any person."
    package, _ = _native_archive(tmp_path, "cargo", "example", "1.2.3", text,
                                 license_filename="LEGAL")
    terms, _, files = _native_license_terms("cargo", package, tmp_path, False)
    assert terms == ["MIT"]
    assert files == [{"name": "example-1.2.3/LEGAL", "sha256": hashlib.sha256(text.encode()).hexdigest(),
                      "text": text}]


@pytest.mark.parametrize("archive_root", ["node", "node v24.13.3"])
def test_npm_archive_root_name_is_not_package_identity(tmp_path, archive_root):
    from scripts.ci.dependency_inventory import _native_license_terms

    package, _ = _native_archive(tmp_path, "npm", "@types/node", "24.13.3", "MIT License",
                                 archive_prefix=archive_root)
    terms, _, files = _native_license_terms("npm", package, tmp_path, False)
    assert terms == ["MIT"]
    assert files[0]["name"] == f"{archive_root}/LICENSE"


def test_wheel_license_evidence_does_not_use_a_longer_version_prefix(tmp_path):
    _wheel(tmp_path, "example", "1.0.1", ["License-Expression: MIT"])
    terms, _, _ = _artifact_license_terms(tmp_path, "example", "1.0")
    assert terms == []


@pytest.mark.parametrize("malformation", ["identity", "duplicate_metadata", "foreign_license", "ambiguous_wheels"])
def test_wheel_license_evidence_refuses_ambiguous_or_foreign_identity(tmp_path, malformation):
    wheel = _wheel(tmp_path, "example", "1.0", ["License-Expression: MIT"])
    if malformation == "identity":
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("example-1.0.dist-info/METADATA",
                             "Name: another\nVersion: 1.0\nLicense-Expression: MIT\n")
    elif malformation == "ambiguous_wheels":
        (tmp_path / "example-1.0-cp312-cp312-linux_x86_64.whl").write_bytes(wheel.read_bytes())
    else:
        with zipfile.ZipFile(wheel, "a") as archive:
            if malformation == "duplicate_metadata":
                archive.writestr("another-1.0.dist-info/METADATA",
                                 "Name: another\nVersion: 1.0\nLicense-Expression: MIT\n")
            else:
                archive.writestr("another-1.0.dist-info/LICENSE", "MIT License")
    with pytest.raises(InventoryError):
        _artifact_license_terms(tmp_path, "example", "1.0")


@pytest.mark.parametrize("field", ["Name", "Version"])
def test_wheel_identity_fields_must_not_be_duplicated(tmp_path, field):
    _wheel(tmp_path, "example", "1.0", ["License-Expression: MIT", f"{field}: another"])
    with pytest.raises(InventoryError, match="duplicate identity"):
        _artifact_license_terms(tmp_path, "example", "1.0")


@pytest.mark.parametrize("local_source", [{"virtual": "."}, {"editable": "."}])
def test_prebuild_project_source_is_opt_in_and_bound_to_committed_files(tmp_path, local_source):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="local-project"\nversion="1.0"\nlicense="MIT"\nlicense-files=["LICENSE"]\n')
    (tmp_path / "LICENSE").write_text("MIT License. Permission is hereby granted to any person.")
    root = _repository(tmp_path, uv='[[package]]\nname="local-project"\nversion="1.0"\nsource=' +
                       ('{virtual="."}' if "virtual" in local_source else '{editable="."}') + '\n')
    ordinary = build_inventory(root, resolve_licenses=True, artifact_dir=tmp_path)
    assert not ordinary["ecosystems"][0]["packages"][0]["licenses"]
    source = build_inventory(root, resolve_licenses=True, artifact_dir=tmp_path, prebuild_local_project=True)
    package = source["ecosystems"][0]["packages"][0]
    assert package["licenses"] == ["MIT"]
    assert package["license_evidence"] == "prebuild-source"
    assert {p["path"] for p in source["ecosystems"][0]["provenance"]} == {"uv.lock", "pyproject.toml", "LICENSE"}
    assert all(p["matches_commit"] for p in source["ecosystems"][0]["provenance"])
    (root / "LICENSE").write_text("uncommitted change")
    dirty = build_inventory(root, resolve_licenses=True, artifact_dir=tmp_path, prebuild_local_project=True)
    assert any(p.get("matches_commit") is False for p in dirty["ecosystems"][0]["provenance"])


@pytest.mark.parametrize("failure", ["identity", "escape", "absent"])
def test_prebuild_source_refuses_wrong_identity_or_unprovable_files(tmp_path, failure):
    from scripts.ci.dependency_inventory import _local_project_license_terms
    name = "wrong-project" if failure == "identity" else "local-project"
    filename = "../LICENSE" if failure == "escape" else "missing-LICENSE"
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname="{name}"\nversion="1.0"\nlicense="MIT"\nlicense-files=["{filename}"]\n')
    root = _repository(tmp_path)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    args = (root, {"name": "local-project", "version": "1.0"}, commit, [])
    if failure != "absent":
        with pytest.raises(InventoryError):
            _local_project_license_terms(*args)
    else:
        assert _local_project_license_terms(*args)[0] == []


def test_registry_package_cannot_borrow_local_project_licence(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="local-project"\nversion="1.0"\nlicense="MIT"\nlicense-files=["LICENSE"]\n')
    (tmp_path / "LICENSE").write_text("MIT License. Permission is hereby granted to any person.")
    root = _repository(tmp_path, uv='[[package]]\nname="local-project"\nversion="1.0"\n'
                       'source={registry="https://pypi.org/simple"}\n')
    result = build_inventory(root, resolve_licenses=True, artifact_dir=tmp_path, prebuild_local_project=True)
    package = result["ecosystems"][0]["packages"][0]
    assert not package["licenses"]
    assert "license_evidence" not in package


def test_wheel_version_prefix_is_not_exact_artifact_evidence(tmp_path):
    """A nearby version cannot supply the pinned package's license evidence."""
    _wheel(tmp_path, "library", "1.0.1", ["License-Expression: MIT"])
    terms, source, files = _artifact_license_terms(tmp_path, "library", "1.0")
    assert terms == []
    assert "no wheel" in source
    assert files == []


@pytest.mark.parametrize("filename", ["LICENSE", "UNLICENSE"])
@pytest.mark.parametrize("linked", [False, True])
def test_installed_license_bytes_reach_inventory_without_import(tmp_path, monkeypatch, linked, filename):
    import importlib.metadata
    repository = _repository(tmp_path)
    site = tmp_path / "site"
    info = site / "only_library-1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text("Name: only_library\nVersion: 1.0\nLicense-Expression: MIT\n")
    raw = b"Permission is hereby granted, free of charge.\r\n"
    license_path = info / filename
    if linked:
        outside = tmp_path / "outside-license"
        outside.write_bytes(raw)
        license_path.symlink_to(outside)
    else:
        license_path.write_bytes(raw)
    (info / "RECORD").write_text(f"only_library-1.0.dist-info/{filename},,\n")
    distribution = importlib.metadata.Distribution.at(info)
    monkeypatch.setattr(importlib.metadata, "distribution", lambda name: distribution)
    inventory = build_inventory(repository, resolve_licenses=True)
    package = next(e for e in inventory["ecosystems"] if e["ecosystem"] == "python")["packages"][0]
    if linked:
        assert package["license_files"] == []
    else:
        assert package["license_files"] == [{"name": filename, "sha256": hashlib.sha256(raw).hexdigest(),
                                            "text": raw.decode("utf-8")}]


@pytest.mark.parametrize("empty_file", [False, True])
def test_wheel_license_directory_is_not_an_empty_instrument(tmp_path, empty_file):
    """ZIP directories are structure; an empty regular licence still holds."""
    from scripts.ci.release_license_gate import classify_inventory_licenses

    wheel = _wheel(tmp_path, "example", "1.0", ["License-Expression: MIT"])
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("example-1.0.dist-info/licenses/", b"")
        archive.writestr("example-1.0.dist-info/licenses/LICENSE",
                         "Permission is hereby granted, free of charge")
        if empty_file:
            archive.writestr("example-1.0.dist-info/licenses/NOTICE", b"")
    terms, _, files = _artifact_license_terms(tmp_path, "example", "1.0")
    assert {file['name'] for file in files} == ({"LICENSE", "NOTICE"} if empty_file else {"LICENSE"})
    groups = classify_inventory_licenses({"ecosystems": [{"ecosystem": "python", "packages": [
        {"name": "example", "version": "1.0", "licenses": terms, "license_files": files}]}]})
    assert bool(groups["permitted"]) is not empty_file


@pytest.mark.parametrize("child_terms", ["MIT", "LGPL-3.0-only", None])
def test_bundled_distribution_has_independent_evidence_and_classification(tmp_path, child_terms):
    from scripts.ci.dependency_inventory import _artifact_distributions
    from scripts.ci.release_license_gate import classify_inventory_licenses

    wheel = _wheel(tmp_path, "example", "1.0", ["License-Expression: MIT"])
    child_root = "example/_vendor/child-2.0.dist-info/"
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("example-1.0.dist-info/LICENSE", "Permission is hereby granted, free of charge")
        declaration = f"License-Expression: {child_terms}\n" if child_terms else ""
        archive.writestr(child_root + "METADATA", "Name: child\nVersion: 2.0\n" + declaration)
        if child_terms:
            archive.writestr(child_root + "LICENSE", "GNU Lesser General Public License" if "LGPL" in child_terms
                             else "Permission is hereby granted, free of charge")
    records = _artifact_distributions(tmp_path, "example", "1.0")
    assert [(r["name"], r["version"]) for r in records] == [("example", "1.0"), ("child", "2.0")]
    assert records[0]["licenses"] == ["MIT"]
    assert records[1]["bundled_in"] == {"name": "example", "version": "1.0"}
    assert records[0]["artifact_sha256"] == records[1]["artifact_sha256"]
    assert all(file["name"].startswith(child_root) for file in records[1]["license_files"])
    groups = classify_inventory_licenses({"ecosystems": [{"ecosystem": "python", "packages": records}]})
    assert len(groups["permitted"]) == (2 if child_terms == "MIT" else 1)
    assert len(groups["copyleft"]) == (1 if child_terms == "LGPL-3.0-only" else 0)
    assert len(groups["undecidable"]) == (1 if child_terms is None else 0)
    with pytest.raises(InventoryError):
        _artifact_license_terms(tmp_path, "example", "1.0")


@pytest.mark.parametrize("failure", ["foreign_license", "nested_evidence_directory", "traversal", "oversized"])
def test_bundled_wheel_refuses_unowned_or_unsafe_evidence(tmp_path, monkeypatch, failure):
    import scripts.ci.dependency_inventory as inventory

    wheel = _wheel(tmp_path, "example", "1.0", ["License-Expression: MIT"])
    with zipfile.ZipFile(wheel, "a") as archive:
        if failure == "foreign_license":
            archive.writestr("foreign-2.0.dist-info/LICENSE", "Permission is hereby granted")
        elif failure == "nested_evidence_directory":
            archive.writestr("example-1.0.dist-info/vendor/child-2.0.dist-info/METADATA",
                             "Name: child\nVersion: 2.0\nLicense-Expression: MIT\n")
        elif failure == "traversal":
            archive.writestr("../example/LICENSE", "Permission is hereby granted")
        else:
            monkeypatch.setattr(inventory, "_NATIVE_TEXT_LIMIT", 1)
    with pytest.raises(InventoryError):
        inventory._artifact_distributions(tmp_path, "example", "1.0")


def test_production_inventory_keeps_bundled_python_scope(tmp_path):
    root = _repository(tmp_path, uv='[[package]]\nname="example"\nversion="1.0"\n')
    wheel = _wheel(tmp_path, "example", "1.0", ["License-Expression: MIT"])
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("example/vendor/child-2.0.dist-info/METADATA",
                         "Name: child\nVersion: 2.0\nLicense-Expression: LGPL-3.0-only\n")
    inventory = build_inventory(root, resolve_licenses=True, artifact_dir=tmp_path)
    packages = inventory["ecosystems"][0]["packages"]
    assert [(p["name"], p["version"]) for p in packages] == [("example", "1.0"), ("child", "2.0")]
    assert packages[1]["purl"] == "pkg:pypi/child@2.0"
    assert packages[1]["sources"] == packages[0]["sources"] == ["uv.lock"]
    assert packages[1]["licenses"] == ["LGPL-3.0-only"]


@pytest.mark.parametrize("bundled", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_declared_arbitrary_license_filename_cannot_hide_additional_terms(tmp_path, bundled, missing):
    from scripts.ci.dependency_inventory import _artifact_distributions
    from scripts.ci.release_license_gate import classify_inventory_licenses

    declarations = [] if bundled else ["License-File: EULA.txt"]
    wheel = _wheel(tmp_path, "example", "1.0", ["License-Expression: MIT", *declarations])
    root = "example/vendor/child-2.0.dist-info/" if bundled else "example-1.0.dist-info/"
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("example-1.0.dist-info/LICENSE", "Permission is hereby granted, free of charge")
        if bundled:
            archive.writestr(root + "METADATA", "Name: child\nVersion: 2.0\nLicense-Expression: MIT\nLicense-File: EULA.txt\n")
            archive.writestr(root + "LICENSE", "Permission is hereby granted, free of charge")
        if not missing:
            archive.writestr(root + "EULA.txt", "GNU Lesser General Public License")
    if missing:
        with pytest.raises(InventoryError, match="missing or ambiguous"):
            _artifact_distributions(tmp_path, "example", "1.0")
        return
    records = _artifact_distributions(tmp_path, "example", "1.0")
    assert any(file["name"].endswith("/EULA.txt") for file in records[-1]["license_files"])
    groups = classify_inventory_licenses({"ecosystems": [{"ecosystem": "python", "packages": records}]})
    assert len(groups["undecidable"]) == 1
    assert len(groups["permitted"]) == int(bundled)


@pytest.mark.parametrize("ecosystem", ["cargo", "npm", "python"])
def test_unlicense_named_file_cannot_hide_additional_copyleft(tmp_path, ecosystem):
    """Read the instrument's bytes; its permissive-looking name grants nothing."""
    from scripts.ci.dependency_inventory import _native_license_terms
    from scripts.ci.release_license_gate import classify_inventory_licenses

    text = "Permission is hereby granted, free of charge, to any person."
    extra = "GNU General Public License version 3 applies to this software."
    if ecosystem == "python":
        wheel = _wheel(tmp_path, "example", "1.2.3", ["License-Expression: MIT"])
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("example-1.2.3.dist-info/LICENSE", text)
            archive.writestr("example-1.2.3.dist-info/UNLICENSE", extra)
        terms, source, files = _artifact_license_terms(tmp_path, "example", "1.2.3")
        package = {"name": "example", "version": "1.2.3"}
    else:
        prefix = "example-1.2.3" if ecosystem == "cargo" else "package"
        package, _ = _native_archive(tmp_path, ecosystem, "example", "1.2.3", text,
                                     extra={f"{prefix}/UNLICENSE": extra})
        terms, source, files = _native_license_terms(ecosystem, package, tmp_path, False)
    assert any(file["name"].endswith("UNLICENSE") for file in files)
    package.update(licenses=terms, license_files=files, license_source=source)
    groups = classify_inventory_licenses({"ecosystems": [{"ecosystem": ecosystem,
                                                          "packages": [package]}]})
    assert not groups["permitted"]
    assert groups["undecidable"] or groups["copyleft"]


def test_bundled_archive_has_separate_identity_and_unresolved_scope(tmp_path):
    """A root MIT instrument does not clear an unseen nested archive."""
    from scripts.ci.dependency_inventory import _artifact_distributions
    from scripts.ci.release_license_gate import classify_inventory_licenses

    wheel = _wheel(tmp_path, "example", "1.0", ["License-Expression: MIT"])
    payload = b"unreviewed nested archive bytes"
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("example-1.0.dist-info/LICENSE", "Permission is hereby granted, free of charge.")
        archive.writestr("example/data/payload.tar.gz", payload)
    records = _artifact_distributions(tmp_path, "example", "1.0")
    assert records[0]["bundled_archives"] == [{
        "name": "example/data/payload.tar.gz", "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload), "license_source": "unresolved nested archive scope",
    }]
    groups = classify_inventory_licenses({"ecosystems": [{"ecosystem": "python", "packages": records}]})
    assert not groups["permitted"]
    assert groups["undecidable"]


def test_nested_archive_size_limit_is_checked_before_read(tmp_path, monkeypatch):
    import scripts.ci.dependency_inventory as inventory

    wheel = _wheel(tmp_path, "example", "1.0", ["License-Expression: MIT"])
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("example/data/payload.tar.gz", b"x" * 4096,
                         compress_type=zipfile.ZIP_DEFLATED)
    assert wheel.stat().st_size < 2048
    monkeypatch.setattr(inventory, "_NATIVE_ARCHIVE_LIMIT", 2048)
    with pytest.raises(InventoryError, match="nested wheel archive exceeds"):
        inventory._artifact_distributions(tmp_path, "example", "1.0")


def test_package_body_license_evidence_cannot_be_hidden_by_root_metadata(tmp_path):
    """Keep separately scoped package evidence without applying the root grant."""
    from scripts.ci.dependency_inventory import _artifact_distributions
    from scripts.ci.release_license_gate import classify_inventory_licenses

    wheel = _wheel(tmp_path, "example", "1.0", ["License-Expression: MIT"])
    payloads = {
        "example/data/cc-by-4.0.LICENSE": b"separately scoped license terms",
        "example/data/index.json.ABOUT": b"about_resource: index.json\nlicense_expression: cc-by-4.0\n",
    }
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("example-1.0.dist-info/LICENSE", "Permission is hereby granted, free of charge.")
        for name, data in payloads.items():
            archive.writestr(name, data)
        archive.writestr("example/license.py", "# source module, not a license instrument\n")
    records = _artifact_distributions(tmp_path, "example", "1.0")
    assert records[0]["unscoped_license_files"] == [
        {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "text": data.decode()}
        for name, data in payloads.items()
    ]
    groups = classify_inventory_licenses({"ecosystems": [{"ecosystem": "python", "packages": records}]})
    assert not groups["permitted"]
    assert "package-body license scope unresolved" in groups["undecidable"][0]["license"]


@pytest.mark.parametrize("ecosystem", ["cargo", "npm"])
def test_native_suffix_instruments_cannot_be_omitted(tmp_path, ecosystem):
    from scripts.ci.dependency_inventory import _native_license_terms
    from scripts.ci.release_license_gate import classify_inventory_licenses

    prefix = "example-1.0" if ecosystem == "cargo" else "package"
    payloads = {
        f"{prefix}/data/extra.LICENSE": "separately scoped terms",
        f"{prefix}/data/index.ABOUT": "about_resource: index.json\nlicense_expression: LicenseRef-unknown\n",
        f"{prefix}/license.js": "// source module, not a grant\n",
        f"{prefix}/license.rs": "// source module, not a grant\n",
    }
    package, _ = _native_archive(tmp_path, ecosystem, "example", "1.0",
                                "Permission is hereby granted, free of charge.", extra=payloads)
    terms, source, files = _native_license_terms(ecosystem, package, tmp_path, False)
    assert {f["name"] for f in files} == {f"{prefix}/LICENSE", *list(payloads)[:2]}
    for f in files:
        if f["name"] in payloads:
            assert f["sha256"] == hashlib.sha256(payloads[f["name"]].encode()).hexdigest()
    package.update(licenses=terms, license_source=source, license_files=files)
    groups = classify_inventory_licenses({"ecosystems": [{"ecosystem": ecosystem, "packages": [package]}]})
    assert not groups["permitted"]
    assert groups["undecidable"]


def test_legacy_dotted_wheel_name_is_normalized_without_hiding_ambiguity(tmp_path):
    from scripts.ci.dependency_inventory import _artifact_distributions

    _wheel(tmp_path, "jaraco.classes", "3.4.0", ["License-Expression: MIT"])
    records = _artifact_distributions(tmp_path, "jaraco-classes", "3.4.0")
    assert len(records) == 1
    assert records[0]["metadata_path"] == "jaraco.classes-3.4.0.dist-info/METADATA"
    assert not _artifact_distributions(tmp_path, "jaraco-classes", "3.4")
    _wheel(tmp_path, "jaraco_classes", "3.4.0", ["License-Expression: MIT"])
    with pytest.raises(InventoryError, match="multiple wheels"):
        _artifact_distributions(tmp_path, "jaraco-classes", "3.4.0")


def test_workspace_license_instruments_stay_within_native_build_boundary():
    """Both maturin generations require a crate-local license instrument."""
    import tomllib

    workspace = REPOSITORY_ROOT / "rust"
    data = tomllib.loads((workspace / "Cargo.toml").read_text())
    for member in data["workspace"]["members"]:
        manifest = workspace / member / "Cargo.toml"
        package = tomllib.loads(manifest.read_text())["package"]
        instrument = (manifest.parent / package["license-file"]).resolve()
        assert instrument.is_relative_to(manifest.parent)
        assert instrument.read_bytes() == (REPOSITORY_ROOT / "LICENSE").read_bytes()
