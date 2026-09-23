"""The non-shipped dependency classes must still be enumerated and bound to a commit.

A release SBOM built from an installed environment cannot see the `dev`, `fuzz`
and `native-build` groups, the Rust workspace or the npm tree. Scoping the SBOM
down does not discharge the licence policy, so those classes are emitted as a
separate inventory carrying the same `source_sha`, and an unprovable scope fails
rather than disappearing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ci.dependency_inventory import build_inventory, main  # noqa: E402

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
