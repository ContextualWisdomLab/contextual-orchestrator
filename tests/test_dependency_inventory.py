"""The non-shipped dependency classes must still be enumerated and bound to a commit.

A release SBOM built from an installed environment cannot see the `dev`, `fuzz`
and `native-build` groups, the Rust workspace or the npm tree. Scoping the SBOM
down does not discharge the licence policy, so those classes are emitted as a
separate inventory carrying the same `source_sha`, and an unprovable scope fails
rather than disappearing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from scripts.ci.dependency_inventory import (  # noqa: E402
    InventoryError,
    _pnpm_packages,
    build_inventory,
    main,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_inventory_covers_every_lockfile_resolved_scope(tmp_path) -> None:
    output = tmp_path / "dependency-inventory.json"

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
    assert {"cyclonedx-bom", "chardet"} <= names  # security CI toolchain
    assert len(python["provenance"]) == len(python["lockfile"].split(", "))
