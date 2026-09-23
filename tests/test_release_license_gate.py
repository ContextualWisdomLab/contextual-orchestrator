"""Contract for the fail-closed release licence gate.

A release must not start tagging or publishing while the artifact's own
CycloneDX SBOM still carries a GPL-family or unknown-licence component. These
cases are the ones the coordinator's policy names explicitly: optional and
unexecuted components are in scope, a dual licence passes only on a real
permissive option, and an unknown licence is a stop rather than a pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ci.release_license_gate import (  # noqa: E402
    classify_sbom_components,
    inventory_binding_findings,
    main,
    scope_coverage_findings,
)


def _sbom(*components: dict) -> dict:
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": list(components)}


def _component(name: str, version: str, *, expression: str | None = None, license_id: str | None = None,
               licenses: list | None = None) -> dict:
    component = {"name": name, "version": version, "type": "library"}
    if licenses is not None:
        component["licenses"] = licenses
    elif expression is not None:
        component["licenses"] = [{"expression": expression}]
    elif license_id is not None:
        component["licenses"] = [{"license": {"id": license_id}}]
    return component


def _write(tmp_path: Path, payload: dict) -> str:
    path = tmp_path / "cyclonedx-sbom.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(
    "license_id",
    ["LGPL-3.0-only", "GPL-2.0-or-later", "AGPL-3.0", "GNU Lesser General Public License v3 (LGPLv3)"],
)
def test_copyleft_component_blocks_the_release(tmp_path, license_id) -> None:
    sbom = _sbom(_component("permitted_library", "1.0", license_id="MIT"),
                 _component("copyleft_library", "3.3.4", license_id=license_id))

    groups = classify_sbom_components(sbom)

    assert [row["name"] for row in groups["copyleft"]] == ["copyleft_library"]
    assert main(["--sbom", _write(tmp_path, sbom)]) == 1


def test_unknown_license_blocks_the_release(tmp_path) -> None:
    """An absent or placeholder licence is a stop, never an implicit pass."""
    sbom = _sbom(_component("undeclared_library", "0.1"),
                 _component("placeholder_library", "0.2", license_id="NOASSERTION"))

    groups = classify_sbom_components(sbom)

    assert {row["name"] for row in groups["undecidable"]} == {"undeclared_library", "placeholder_library"}
    assert main(["--sbom", _write(tmp_path, sbom)]) == 1


def test_permissive_only_sbom_passes(tmp_path) -> None:
    sbom = _sbom(_component("mit_library", "1.0", license_id="MIT"),
                 _component("apache_library", "2.0", license_id="Apache-2.0"),
                 _component("mozilla_library", "3.0", license_id="MPL-2.0"))

    assert main(["--sbom", _write(tmp_path, sbom)]) == 0


def test_dual_license_passes_only_on_a_real_permissive_option(tmp_path) -> None:
    choosable = _sbom(_component("dual_choice_library", "1.0", expression="Apache-2.0 OR GPL-2.0-only"))
    conjunctive = _sbom(_component("dual_conjunct_library", "1.0", expression="Apache-2.0 AND GPL-2.0-only"))

    assert main(["--sbom", _write(tmp_path, choosable)]) == 0
    assert classify_sbom_components(conjunctive)["copyleft"][0]["name"] == "dual_conjunct_library"


def test_empty_component_set_is_not_evidence_of_cleanliness(tmp_path) -> None:
    assert main(["--sbom", _write(tmp_path, {"bomFormat": "CycloneDX", "components": []})]) == 1


def test_missing_sbom_file_fails_closed(tmp_path) -> None:
    assert main(["--sbom", str(tmp_path / "absent.json")]) == 1


def test_release_workflow_runs_the_gate_before_publishing() -> None:
    """The gate must sit in `verify`, which `publish` depends on, after the SBOM download."""
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
    text = workflow.read_text(encoding="utf-8")

    verify_block = text[text.index("\n  verify:") : text.index("\n  publish:")]
    assert "scripts.ci.release_license_gate" in verify_block
    assert verify_block.index("Fetch the required CycloneDX SBOM") < verify_block.index(
        "scripts.ci.release_license_gate"
    )
    publish_block = text[text.index("\n  publish:") :]
    assert "needs: verify" in publish_block


# --- negative regressions for the fail-open cases found in independent review ---


@pytest.mark.parametrize(
    "component",
    [
        pytest.param(_component("licenseref_library", "1.0", license_id="LicenseRef-Unreviewed"), id="license_ref"),
        pytest.param(_component("free_text_library", "1.0", license_id="GPLv3"), id="free_text_gplv3"),
        pytest.param(_component("or_unknown_library", "1.0", expression="GPL-3.0-only OR UNKNOWN"), id="or_unknown"),
        pytest.param(
            _component(
                "conjunctive_entries_library",
                "1.0",
                licenses=[{"expression": "MIT OR GPL-2.0-only"}, {"license": {"id": "AGPL-3.0-only"}}],
            ),
            id="separate_entries_are_conjunctive",
        ),
    ],
)
def test_fail_open_cases_are_refused(tmp_path, component) -> None:
    """Each of these passed an earlier gate revision; none may pass again."""
    assert main(["--sbom", _write(tmp_path, _sbom(component))]) == 1


def test_malformed_component_entry_fails_closed(tmp_path) -> None:
    """A null component means the SBOM cannot be read, which is not a pass."""
    sbom = {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": [None]}

    assert main(["--sbom", _write(tmp_path, sbom)]) == 1


def test_nested_component_is_classified(tmp_path) -> None:
    """A GPL dependency nested under a permitted parent still blocks."""
    parent = _component("permitted_parent_library", "1.0", license_id="MIT")
    parent["components"] = [_component("nested_copyleft_library", "2.0", license_id="GPL-3.0-only")]

    groups = classify_sbom_components(_sbom(parent))

    assert [row["name"] for row in groups["copyleft"]] == ["nested_copyleft_library"]
    assert main(["--sbom", _write(tmp_path, _sbom(parent))]) == 1


def test_permissive_zero_clause_licence_still_passes(tmp_path) -> None:
    """MIT-0 must not be mistaken for a copyleft identifier by the matcher."""
    sbom = _sbom(_component("zero_clause_library", "1.0", license_id="MIT-0"))

    assert main(["--sbom", _write(tmp_path, sbom)]) == 0


def test_declared_dependency_absent_from_the_sbom_fails_closed(tmp_path) -> None:
    """A partial SBOM is not evidence about the scopes it never collected."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "x"\nversion = "0.0.1"\ndependencies = ["collected_library>=1"]\n'
        '[project.optional-dependencies]\ndb = ["absent_library>=2"]\n',
        encoding="utf-8",
    )
    sbom = _sbom(_component("collected_library", "1.0", license_id="MIT"))

    assert main(["--sbom", _write(tmp_path, sbom), "--pyproject", str(pyproject)]) == 1


def test_full_declared_coverage_passes(tmp_path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "x"\nversion = "0.0.1"\ndependencies = ["Collected.Library>=1"]\n'
        '[dependency-groups]\ndev = ["grouped_library"]\n',
        encoding="utf-8",
    )
    sbom = _sbom(_component("collected-library", "1.0", license_id="MIT"),
                 _component("grouped_library", "2.0", license_id="BSD-3-Clause"))

    assert main(["--sbom", _write(tmp_path, sbom), "--pyproject", str(pyproject)]) == 0


def _repository(tmp_path: Path) -> Path:
    """A miniature repository carrying one lockfile per shipped ecosystem."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "gate_fixture_project"\nversion = "0.0.1"\ndependencies = ["direct_library>=1"]\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "direct_library"\nversion = "1.0"\n\n'
        '[[package]]\nname = "transitive_library"\nversion = "2.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "rust").mkdir(exist_ok=True)
    (tmp_path / "rust" / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    (tmp_path / "rust" / "Cargo.lock").write_text(
        '[[package]]\nname = "one_cargo_crate"\nversion = "1.1.5"\n\n'
        '[[package]]\nname = "other_cargo_crate"\nversion = "0.3.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text('{"name": "gate_fixture_project"}', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text(
        json.dumps({"lockfileVersion": 3, "packages": {
            "": {"name": "gate_fixture_project"},
            "node_modules/one_npm_package": {"version": "1.0.0"},
            "node_modules/other_npm_package": {"version": "4.2.0"},
        }}),
        encoding="utf-8",
    )
    return tmp_path


def _purl_component(name: str, version: str, purl: str) -> dict:
    component = _component(name, version, license_id="MIT")
    component["purl"] = purl
    return component


def test_native_manifest_without_sbom_coverage_fails_closed(tmp_path) -> None:
    """Rust and npm manifests ship in the image, so the SBOM must cover them."""
    repository = _repository(tmp_path)
    sbom = _sbom(_purl_component("direct_library", "1.0", "pkg:pypi/direct_library@1.0"),
                 _purl_component("transitive_library", "2.0", "pkg:pypi/transitive_library@2.0"))

    assert main(["--sbom", _write(tmp_path, sbom), "--pyproject", str(repository / "pyproject.toml"),
                 "--repository-root", str(repository)]) == 1


def test_one_component_per_ecosystem_does_not_prove_coverage(tmp_path) -> None:
    """The reviewer's repro: every direct name plus one purl per ecosystem passed before."""
    repository = _repository(tmp_path)
    sbom = _sbom(
        _purl_component("direct_library", "1.0", "pkg:pypi/direct_library@1.0"),
        _purl_component("transitive_library", "2.0", "pkg:pypi/transitive_library@2.0"),
        _purl_component("one_cargo_crate", "1.1.5", "pkg:cargo/one_cargo_crate@1.1.5"),
        _purl_component("one_npm_package", "1.0.0", "pkg:npm/one_npm_package@1.0.0"),
    )

    findings = scope_coverage_findings(json.loads(json.dumps(sbom)),
                                       str(repository / "pyproject.toml"), str(repository))

    assert [finding.split(":")[0] for finding in findings] == ["cargo", "npm"]
    assert "other-cargo-crate==0.3.0" in findings[0]
    assert "other-npm-package==4.2.0" in findings[1]
    assert main(["--sbom", _write(tmp_path, sbom), "--pyproject", str(repository / "pyproject.toml"),
                 "--repository-root", str(repository)]) == 1


def test_complete_ecosystem_sets_pass(tmp_path) -> None:
    repository = _repository(tmp_path)
    sbom = _sbom(
        _purl_component("direct_library", "1.0", "pkg:pypi/direct_library@1.0"),
        _purl_component("transitive_library", "2.0", "pkg:pypi/transitive_library@2.0"),
        _purl_component("one_cargo_crate", "1.1.5", "pkg:cargo/one_cargo_crate@1.1.5"),
        _purl_component("other_cargo_crate", "0.3.0", "pkg:cargo/other_cargo_crate@0.3.0"),
        _purl_component("one_npm_package", "1.0.0", "pkg:npm/one_npm_package@1.0.0"),
        _purl_component("other_npm_package", "4.2.0", "pkg:npm/other_npm_package@4.2.0"),
    )

    assert main(["--sbom", _write(tmp_path, sbom), "--pyproject", str(repository / "pyproject.toml"),
                 "--repository-root", str(repository)]) == 0


def test_missing_lockfile_is_an_unprovable_scope(tmp_path) -> None:
    repository = _repository(tmp_path)
    (repository / "rust" / "Cargo.lock").unlink()
    sbom = _sbom(_purl_component("direct_library", "1.0", "pkg:pypi/direct_library@1.0"),
                 _purl_component("transitive_library", "2.0", "pkg:pypi/transitive_library@2.0"),
                 _purl_component("one_npm_package", "1.0.0", "pkg:npm/one_npm_package@1.0.0"),
                 _purl_component("other_npm_package", "4.2.0", "pkg:npm/other_npm_package@4.2.0"))

    findings = scope_coverage_findings(sbom, str(repository / "pyproject.toml"), str(repository))

    assert any("cannot be proven" in finding for finding in findings)
    assert main(["--sbom", _write(tmp_path, sbom), "--pyproject", str(repository / "pyproject.toml"),
                 "--repository-root", str(repository)]) == 1


def test_empty_lock_set_is_not_proof_of_no_dependencies(tmp_path) -> None:
    """A lockfile that resolves nothing while its manifest declares work is unprovable."""
    repository = _repository(tmp_path)
    (repository / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (repository / "rust" / "Cargo.lock").write_text("version = 4\n", encoding="utf-8")
    (repository / "package-lock.json").write_text(json.dumps({"packages": {}}), encoding="utf-8")
    (repository / "package.json").write_text('{"dependencies": {"one_npm_package": "1.0.0"}}', encoding="utf-8")
    sbom = _sbom(_purl_component("direct_library", "1.0", "pkg:pypi/direct_library@1.0"))

    findings = scope_coverage_findings(sbom, str(repository / "pyproject.toml"), str(repository))

    assert {finding.split(":")[0] for finding in findings} >= {"python", "cargo", "npm"}
    assert main(["--sbom", _write(tmp_path, sbom), "--pyproject", str(repository / "pyproject.toml"),
                 "--repository-root", str(repository)]) == 1


def test_purl_identity_must_match_the_component_fields(tmp_path) -> None:
    """Coverage is read from the purl, so a purl naming something else is a mismatch."""
    repository = _repository(tmp_path)
    sbom = _sbom(
        _purl_component("direct_library", "1.0", "pkg:pypi/unrelated@999"),
        _purl_component("transitive_library", "2.0", "pkg:pypi/unrelated@999"),
        _purl_component("one_cargo_crate", "1.1.5", "pkg:cargo/unrelated@999"),
        _purl_component("other_cargo_crate", "0.3.0", "pkg:cargo/unrelated@999"),
        _purl_component("one_npm_package", "1.0.0", "pkg:npm/unrelated@999"),
        _purl_component("other_npm_package", "4.2.0", "pkg:npm/unrelated@999"),
    )

    findings = scope_coverage_findings(sbom, str(repository / "pyproject.toml"), str(repository))

    assert any("purl" in finding for finding in findings)
    assert main(["--sbom", _write(tmp_path, sbom), "--pyproject", str(repository / "pyproject.toml"),
                 "--repository-root", str(repository)]) == 1


# --- the gate must actually consume the inventory it asks for ---


def _inventory(source_sha: str = "a" * 40, *, matches: bool = True, packages=None) -> dict:
    return {
        "schema": "contextual-orchestrator/dependency-inventory/v1",
        "source_sha": source_sha,
        "ecosystems": [
            {
                "ecosystem": "python",
                "lockfile": "uv.lock",
                "provenance": [{"path": "uv.lock", "read_sha256": "x", "matches_commit": matches}],
                "packages": packages if packages is not None else [{"name": "inventory_only_library", "version": "3.0"}],
            }
        ],
    }


def test_inventory_expectations_replace_the_lockfile_reading(tmp_path) -> None:
    """A package the inventory carries and the SBOM lacks blocks the release."""
    repository = _repository(tmp_path)
    inventory_path = tmp_path / "dependency-inventory.json"
    inventory_path.write_text(json.dumps(_inventory()), encoding="utf-8")
    sbom = _sbom(_purl_component("direct_library", "1.0", "pkg:pypi/direct_library@1.0"),
                 _purl_component("transitive_library", "2.0", "pkg:pypi/transitive_library@2.0"),
                 _purl_component("one_cargo_crate", "1.1.5", "pkg:cargo/one_cargo_crate@1.1.5"),
                 _purl_component("other_cargo_crate", "0.3.0", "pkg:cargo/other_cargo_crate@0.3.0"),
                 _purl_component("one_npm_package", "1.0.0", "pkg:npm/one_npm_package@1.0.0"),
                 _purl_component("other_npm_package", "4.2.0", "pkg:npm/other_npm_package@4.2.0"))

    findings = scope_coverage_findings(sbom, str(repository / "pyproject.toml"), str(repository),
                                       json.loads(inventory_path.read_text(encoding="utf-8")))

    assert any("inventory-only-library==3.0" in finding for finding in findings)
    assert main(["--sbom", _write(tmp_path, sbom), "--pyproject", str(repository / "pyproject.toml"),
                 "--repository-root", str(repository), "--inventory", str(inventory_path)]) == 1


def test_inventory_bound_to_another_commit_is_refused() -> None:
    findings = inventory_binding_findings(_inventory("b" * 40), "c" * 40)

    assert any("does not match the released commit" in finding for finding in findings)


def test_inventory_with_modified_lock_bytes_is_refused() -> None:
    findings = inventory_binding_findings(_inventory(matches=False), "a" * 40)

    assert any("does not match its committed blob" in finding for finding in findings)


def test_inventory_without_source_sha_is_refused() -> None:
    findings = inventory_binding_findings(_inventory(""), None)

    assert any("no source_sha" in finding for finding in findings)
