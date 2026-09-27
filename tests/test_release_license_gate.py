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
    classify_inventory_licenses,
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
    # Two adjudications, in this order: the inventory before any environment is
    # built, and the full gate once the SBOM for this commit is in hand.
    preinstall = verify_block.index("--mode preinstall")
    environment = verify_block.index("uv sync --locked")
    sbom_fetch = verify_block.index("Fetch the required CycloneDX SBOM")
    release_gate = verify_block.index("--sbom sbom-download/cyclonedx-sbom.json")
    assert preinstall < environment < sbom_fetch < release_gate
    assert verify_block.index("--check-sources-only") < preinstall
    download = verify_block.index("collect_python_license_artifacts.sh")
    artifact_read = verify_block.index("--artifact-dir license-artifacts")
    assert verify_block.index("--check-sources-only") < download < artifact_read < preinstall
    collector = workflow.parents[2] / "scripts/ci/collect_python_license_artifacts.sh"
    assert "--only-binary=:all:" in collector.read_text()
    wheel_stage = verify_block.index('cp "${wheel}" license-artifacts/')
    final_read = verify_block.rindex("--artifact-dir license-artifacts")
    assert environment < wheel_stage < final_read < release_gate
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


def _provenance(**overrides) -> dict:
    provenance = {
        "path": "uv.lock",
        "read_sha256": "b" * 64,
        "blob_id": "c" * 40,
        "committed_blob_id": "c" * 40,
        "matches_commit": True,
    }
    provenance.update(overrides)
    return provenance


def _inventory(source_sha: str = "a" * 40, *, provenance=None, packages=None, **overrides) -> dict:
    inventory = {
        "schema": "contextual-orchestrator/dependency-inventory/v1",
        "source_sha": source_sha,
        "ecosystems": [
            {
                "ecosystem": "python",
                "lockfile": "uv.lock",
                "provenance": [_provenance()] if provenance is None else provenance,
                "packages": packages if packages is not None
                else [{"name": "inventory_only_library", "version": "3.0"}],
            }
        ],
    }
    inventory.update(overrides)
    return inventory


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
    findings = inventory_binding_findings(
        _inventory(provenance=[_provenance(matches_commit=False)]), "a" * 40)

    assert any("not marked as matching its commit" in finding for finding in findings)


def test_inventory_without_source_sha_is_refused() -> None:
    findings = inventory_binding_findings(_inventory(""), None)

    assert any("binds to nothing" in finding for finding in findings)


@pytest.mark.parametrize(
    "inventory, expected_fragment",
    [
        pytest.param(_inventory(provenance=[_provenance(blob_id="d" * 40)]),
                     "differs from the committed", id="blob_ids_disagree_despite_true_flag"),
        pytest.param(_inventory(provenance=[_provenance(read_sha256="not-a-hash")]),
                     "no usable read_sha256", id="unusable_read_hash"),
        pytest.param(_inventory(provenance=[_provenance(matches_commit="false")]),
                     "not marked as matching", id="string_false_is_not_true"),
        pytest.param(_inventory(provenance=[]), "no provenance recorded", id="provenance_absent"),
        pytest.param(_inventory(schema="something-else"), "unrecognised schema", id="wrong_schema"),
        pytest.param(_inventory("not-a-commit"), "binds to nothing", id="malformed_source_sha"),
    ],
)
def test_self_contradicting_inventory_is_refused(inventory, expected_fragment) -> None:
    """A recorded verdict is not evidence: the ids and flags are checked here."""
    findings = inventory_binding_findings(inventory, "a" * 40)

    assert any(expected_fragment in finding for finding in findings), findings


def test_inventory_entries_are_adjudicated_not_exempted() -> None:
    """Scopes outside the shipped artefact are judged by the same rules."""
    inventory = _inventory(packages=[
        {"name": "permitted_library", "version": "1.0", "licenses": ["MIT"],
         "license_files": [{"name": "LICENSE", "sha256": "a" * 64,
                            "text": "MIT License\n\nPermission is hereby granted"}]},
        {"name": "copyleft_library", "version": "2.0", "licenses": ["LGPL-3.0-only"]},
        {"name": "unresolved_library", "version": "3.0", "licenses": [],
         "license_source": "unresolved: absent from this environment"},
    ])

    groups = classify_inventory_licenses(inventory)

    assert [row["name"] for row in groups["copyleft"]] == ["python:copyleft_library"]
    assert [row["name"] for row in groups["undecidable"]] == ["python:unresolved_library"]
    assert [row["name"] for row in groups["permitted"]] == ["python:permitted_library"]


def test_inventory_copyleft_blocks_even_when_the_sbom_is_clean(tmp_path) -> None:
    repository = _repository(tmp_path)
    inventory_path = tmp_path / "dependency-inventory.json"
    inventory_path.write_text(json.dumps(_inventory(packages=[
        {"name": "direct_library", "version": "1.0", "licenses": ["GPL-3.0-only"]},
    ])), encoding="utf-8")
    sbom = _sbom(_purl_component("direct_library", "1.0", "pkg:pypi/direct_library@1.0"),
                 _purl_component("transitive_library", "2.0", "pkg:pypi/transitive_library@2.0"),
                 _purl_component("one_cargo_crate", "1.1.5", "pkg:cargo/one_cargo_crate@1.1.5"),
                 _purl_component("other_cargo_crate", "0.3.0", "pkg:cargo/other_cargo_crate@0.3.0"),
                 _purl_component("one_npm_package", "1.0.0", "pkg:npm/one_npm_package@1.0.0"),
                 _purl_component("other_npm_package", "4.2.0", "pkg:npm/other_npm_package@4.2.0"))

    assert main(["--sbom", _write(tmp_path, sbom), "--pyproject", str(repository / "pyproject.toml"),
                 "--repository-root", str(repository), "--inventory", str(inventory_path),
                 "--source-sha", "a" * 40]) == 1


@pytest.mark.parametrize(
    "package, expected_group",
    [
        pytest.param({"name": "with_text", "version": "1", "licenses": ["MIT"],
                      "license_files": [{"name": "LICENSE", "sha256": "a" * 64,
                                         "text": "MIT License\n\nPermission is hereby granted"}]},
                     "permitted", id="declaration_with_text"),
        pytest.param({"name": "filename_only", "version": "1", "licenses": ["MIT"],
                      "license_files": ["LICENSE"]}, "undecidable", id="filename_without_text"),
        pytest.param({"name": "declaration_only", "version": "1", "licenses": ["MIT"],
                      "license_files": []}, "undecidable", id="declaration_without_text"),
        pytest.param({"name": "conflicting", "version": "1", "licenses": ["MIT", "GPL-3.0-only"],
                      "license_files": [{"name": "LICENSE", "sha256": "a" * 64, "text": "MIT"}]},
                     "copyleft", id="conflicting_terms"),
        pytest.param({"name": "no_wheel", "version": "1", "licenses": [],
                      "license_source": "unresolved: no wheel"}, "undecidable", id="unresolved"),
    ],
)
def test_permitted_terms_alone_never_settle_an_entry(package, expected_group) -> None:
    """A permitted licence line without the artefact's own text is still held."""
    groups = classify_inventory_licenses(_inventory(packages=[package]))

    assert [row["name"] for row in groups[expected_group]] == [f"python:{package['name']}"]
    for other in set(groups) - {expected_group}:
        assert groups[other] == []


def test_declaration_only_entry_blocks_the_gate(tmp_path) -> None:
    repository = _repository(tmp_path)
    inventory_path = tmp_path / "dependency-inventory.json"
    inventory_path.write_text(json.dumps(_inventory(packages=[
        {"name": "direct_library", "version": "1.0", "licenses": ["MIT"], "license_files": []},
    ])), encoding="utf-8")
    sbom = _sbom(_purl_component("direct_library", "1.0", "pkg:pypi/direct_library@1.0"),
                 _purl_component("transitive_library", "2.0", "pkg:pypi/transitive_library@2.0"),
                 _purl_component("one_cargo_crate", "1.1.5", "pkg:cargo/one_cargo_crate@1.1.5"),
                 _purl_component("other_cargo_crate", "0.3.0", "pkg:cargo/other_cargo_crate@0.3.0"),
                 _purl_component("one_npm_package", "1.0.0", "pkg:npm/one_npm_package@1.0.0"),
                 _purl_component("other_npm_package", "4.2.0", "pkg:npm/other_npm_package@4.2.0"))

    assert main(["--sbom", _write(tmp_path, sbom), "--pyproject", str(repository / "pyproject.toml"),
                 "--repository-root", str(repository), "--inventory", str(inventory_path),
                 "--source-sha", "a" * 40]) == 1


def test_licence_text_must_evidence_the_declaration() -> None:
    """A GPL text under an MIT declaration is a contradiction, not a pass."""
    def package(name, text):
        return {"name": name, "version": "1", "licenses": ["MIT"],
                "license_files": [{"name": "LICENSE", "sha256": "x" * 64, "text": text}]}

    groups = classify_inventory_licenses(_inventory(packages=[
        package("matching_library", "MIT License Permission is hereby granted, free of charge"),
        package("contradicted_library", "GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007"),
        {"name": "empty_text_library", "version": "1", "licenses": ["MIT"],
         "license_files": [{"name": "LICENSE", "sha256": "y" * 64, "text": ""}]},
        package("trailing_copyleft_library",
                "MIT License Permission is hereby granted. Module X is under the "
                "GNU General Public License version 3."),
    ]))

    assert [row["name"] for row in groups["permitted"]] == ["python:matching_library"]
    assert {row["name"] for row in groups["undecidable"]} == {
        "python:contradicted_library", "python:empty_text_library",
        "python:trailing_copyleft_library"}


@pytest.mark.parametrize(
    "package, expected",
    [
        pytest.param({"name": "mixed_unknown", "version": "1", "licenses": ["MIT", "LicenseRef-Private"],
                      "license_files": [{"name": "LICENSE", "sha256": "a" * 64,
                                         "text": "MIT License Permission is hereby granted"}]},
                     "undecidable", id="permitted_beside_unknown"),
        pytest.param({"name": "two_texts", "version": "1", "licenses": ["MIT"],
                      "license_files": [
                          {"name": "LICENSE", "sha256": "a" * 64,
                           "text": "MIT License Permission is hereby granted"},
                          {"name": "LICENSE.gpl", "sha256": "b" * 64,
                           "text": "GNU GENERAL PUBLIC LICENSE Version 2, June 1991"}]},
                     "undecidable", id="permissive_text_beside_a_copyleft_one"),
        pytest.param({"name": "restricted", "version": "1", "licenses": ["MIT"],
                      "license_files": [{"name": "LICENSE", "sha256": "a" * 64,
                                         "text": "MIT License Permission is hereby granted. "
                                                 "Commercial use is prohibited."}]},
                     "undecidable", id="restriction_clause"),
        pytest.param({"name": "submit_restricted", "version": "1", "licenses": ["MIT"],
                      "license_files": [{"name": "LICENSE", "sha256": "a" * 64,
                                         "text": "MIT License Permission is hereby granted. "
                                                 "SUBMIT-RESTRICTED: internal use only."}]},
                     "undecidable", id="submit_restricted"),
    ],
)
def test_one_unmet_condition_holds_the_entry(package, expected) -> None:
    """Any single unresolved or restricting condition holds, whatever else passes."""
    groups = classify_inventory_licenses(_inventory(packages=[package]))

    assert [row["name"] for row in groups[expected]] == [f"python:{package['name']}"]


@pytest.mark.parametrize("expression", ["Apache-2.0 WITH LLVM-exception", "MPL-2.0", "BlueOak-1.0.0"])
def test_complete_canonical_license_instrument_is_not_rejected_by_keyword_mentions(expression):
    """An entire known instrument evidences its declaration, including compatibility clauses."""
    text = (Path(__file__).parent / "fixtures/license_text" / f"{expression.replace(' ', '_')}.txt").read_text()
    package = {"name": "example", "version": "1", "licenses": [expression],
               "license_files": [{"name": "LICENSE", "text": text}]}
    groups = classify_inventory_licenses({"ecosystems": [{"ecosystem": "cargo", "packages": [package]}]})
    assert len(groups["permitted"]) == 1
    assert not groups["undecidable"] and not groups["copyleft"]


@pytest.mark.parametrize("expression", ["Apache-2.0 WITH LLVM-exception", "MPL-2.0", "BlueOak-1.0.0"])
@pytest.mark.parametrize("change", ["append", "truncate", "second_file", "second_unknown_file", "wrong_declaration"])
def test_canonical_text_matching_cannot_hide_changed_or_additional_terms(expression, change):
    text = (Path(__file__).parent / "fixtures/license_text" / f"{expression.replace(' ', '_')}.txt").read_text()
    files = [{"name": "LICENSE", "text": text}]
    if change == "append":
        files[0]["text"] += "\nAn additional unreviewed condition applies."
    elif change == "truncate":
        files[0]["text"] = text[:len(text) // 2]
    elif change == "second_file":
        files.append({"name": "COPYING", "text": "GNU Lesser General Public License, version 3"})
    elif change == "second_unknown_file":
        files.append({"name": "NOTICE", "text": "An additional unreviewed condition applies."})
    elif change == "wrong_declaration":
        expression = "GPL-3.0-only"
    package = {"name": "example", "version": "1", "licenses": [expression], "license_files": files}
    groups = classify_inventory_licenses({"ecosystems": [{"ecosystem": "cargo", "packages": [package]}]})
    assert not groups["permitted"]
    assert groups["undecidable"] or groups["copyleft"]


def test_verified_llvm_archive_title_and_whitespace_variants_preserve_complete_matching():
    text = (Path(__file__).parent / "fixtures/license_text/Apache-2.0_WITH_LLVM-exception.txt").read_text()
    text = text.replace("---- LLVM Exceptions", "--- LLVM Exceptions", 1)
    text = " \n".join(text.split())
    package = {"name": "example", "version": "1", "licenses": ["Apache-2.0 WITH LLVM-exception"],
               "license_files": [{"name": "LICENSE", "text": text}]}
    groups = classify_inventory_licenses({"ecosystems": [{"ecosystem": "cargo", "packages": [package]}]})
    assert len(groups["permitted"]) == 1


def test_prebuild_source_cannot_authorize_final_release(tmp_path, monkeypatch, capsys):
    import scripts.ci.release_license_gate as gate
    inventory = {"ecosystems": [{"ecosystem": "python", "packages": [
        {"name": "local-project", "version": "1", "licenses": ["MIT"],
         "license_evidence": "prebuild-source"}]}]}
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(inventory))
    monkeypatch.setattr(gate, "inventory_binding_findings", lambda *args: [])
    monkeypatch.setattr(gate, "scope_coverage_findings", lambda *args: [])
    monkeypatch.setattr(gate, "classify_inventory_licenses", lambda *args: {
        "permitted": [{"name": "local-project", "version": "1", "license": "MIT"}],
        "copyleft": [], "undecidable": []})
    assert gate.main(["--inventory", str(path), "--mode", "preinstall"]) == 0
    sbom = tmp_path / "sbom.json"
    sbom.write_text(json.dumps({"components": [_component("local-project", "1", license_id="MIT")]}))
    assert gate.main(["--inventory", str(path), "--mode", "release", "--sbom", str(sbom)]) == 1
    assert "not final wheel" in capsys.readouterr().out


@pytest.mark.parametrize("mode, expected", [("preinstall", 0), ("release", 1)])
def test_release_requires_sbom_even_with_valid_inventory(tmp_path, mode, expected):
    """Only the preinstall gate may operate without a built-environment SBOM."""
    package = {"name": "library", "version": "1", "licenses": ["MIT"],
               "license_files": [{"text": "Permission is hereby granted, free of charge"}]}
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(_inventory(packages=[package])))
    assert main(["--mode", mode, "--inventory", str(path), "--source-sha", "a" * 40]) == expected


@pytest.mark.parametrize("files", [
    [{"text": "Vendor EULA: submission is permitted subject to vendor terms."}],
    [{"text": "Permission is hereby granted, free of charge"}, {"text": "Vendor EULA"}],
    [{"text": "Permission is hereby granted, free of charge"}, None],
])
def test_every_license_text_must_evidence_the_declared_family(files):
    """Unrelated words and a valid sibling must not certify unknown text."""
    package = {"name": "library", "version": "1", "licenses": ["MIT"], "license_files": files}
    groups = classify_inventory_licenses(_inventory(packages=[package]))
    assert not groups["permitted"]
    assert len(groups["undecidable"]) == 1


def test_nested_scoped_npm_identity_matches_sbom(tmp_path):
    from scripts.ci.release_license_gate import _lock_packages_from_npm, _sbom_packages
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps({"packages": {"node_modules/a/node_modules/@types/node": {"version": "1.0"}}}))
    expected = _lock_packages_from_npm(lock)
    present, mismatches = _sbom_packages([{"group": "@types", "name": "node", "version": "1.0",
                                        "purl": "pkg:npm/%40types/node@1.0"}], "pkg:npm/")
    assert expected == present == {("@types/node", "1.0")}
    assert mismatches == []


def test_malformed_npm_dependency_is_not_silently_dropped(tmp_path):
    from scripts.ci.dependency_inventory import InventoryError
    from scripts.ci.release_license_gate import _lock_packages_from_npm
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps({"packages": {"node_modules/library": None}}))
    with pytest.raises(InventoryError):
        _lock_packages_from_npm(lock)


@pytest.mark.parametrize("unknown", ["Vendor-MIT-Restricted", "BSD-Proprietary", "CustomCompanyTerms"])
@pytest.mark.parametrize("form", ["{}", "MIT OR {}", "MIT AND {}"])
def test_unknown_declaration_never_inherits_permissive_permission(unknown, form):
    """Unknown operands stay held even beside a real permissive declaration."""
    term = form.format(unknown)
    component = _component("example", "1", expression=term)
    assert classify_sbom_components(_sbom(component))["undecidable"]
    package = {"name": "example", "version": "1", "licenses": [term],
               "license_files": [{"name": "LICENSE", "text":
                                  "Permission is hereby granted, free of charge."}]}
    groups = classify_inventory_licenses({"ecosystems": [{"ecosystem": "python",
                                                          "packages": [package]}]})
    assert not groups["permitted"]
    assert groups["undecidable"]


@pytest.mark.parametrize("term", [
    "MIT No Attribution License (MIT-0)",
    "Mozilla Public License 2.0 (MPL 2.0)",
    "Apache License, Version 2.0",
    "(MIT OR Apache-2.0) AND Unicode-3.0",
])
def test_registered_metadata_spellings_remain_recognized(term):
    """Explicit known aliases survive conservative expression normalization."""
    from scripts.ci.release_license_gate import classify_license_term

    assert classify_license_term(term)[0] == "permitted"


def test_ambiguous_dual_license_marker_remains_undecidable():
    from scripts.ci.release_license_gate import classify_license_term

    assert classify_license_term("Dual License")[0] == "undecidable"


@pytest.mark.parametrize("change", ["none", "notice-only", "missing-mit", "missing-unlicense", "changed", "gpl"])
def test_complete_reviewed_dual_instrument_set(change):
    from scripts.ci.release_license_gate import _declaration_matches_text
    directory = Path(__file__).parent / "fixtures" / "license_text"
    texts = [(directory / name).read_text() for name in
             ("dual-selection.txt", "dual-mit.txt", "dual-unlicense.txt")]
    if change == "notice-only":
        texts = texts[:1]
    elif change == "missing-mit":
        del texts[1]
    elif change == "missing-unlicense":
        del texts[2]
    elif change == "changed":
        texts[0] += "Commercial use is prohibited."
    elif change == "gpl":
        texts.append("GNU General Public License version 3")
    assert _declaration_matches_text(["Unlicense OR MIT"], [{"text": t} for t in texts]) is (change == "none")


@pytest.mark.parametrize("name,term", [("cryptography", "Apache-2.0 OR BSD-3-Clause"), ("packaging", "Apache-2.0 OR BSD-2-Clause")])
@pytest.mark.parametrize("change", ["none", "notice-only", "missing-grant", "restriction", "extra"])
def test_complete_apache_bsd_instrument_sets(name, term, change):
    from scripts.ci.release_license_gate import _declaration_matches_text
    directory = Path(__file__).parent / "fixtures" / "license_text"
    texts = [(directory / f"{name}-instrument-{i}.txt").read_text() for i in range(3)]
    if change == "notice-only":
        texts = texts[:1]
    elif change == "missing-grant":
        del texts[1]
    elif change == "restriction":
        texts[0] += "Redistribution requires written permission."
    elif change == "extra":
        texts.append("Unreviewed additional terms")
    assert _declaration_matches_text([term], [{"text": t} for t in texts]) is (change == "none")


def test_complete_blueoak_markdown_variant_preserves_all_terms():
    from scripts.ci.release_license_gate import _declaration_matches_text
    directory = Path(__file__).parent / "fixtures" / "license_text"
    text = (directory / "BlueOak-1.0.0-markdown.txt").read_text()
    canonical = (directory / "BlueOak-1.0.0.txt").read_text()
    rendered = text.replace("**_As far as", "***As far as").replace("claim._**", "claim.***")
    assert " ".join(rendered.split()) == " ".join(canonical.split())
    assert _declaration_matches_text(["BlueOak-1.0.0"], [{"text": text}])
    assert not _declaration_matches_text(["BlueOak-1.0.0"], [{"text": text + "Commercial use forbidden."}])


@pytest.mark.parametrize("change", ["none", "missing-mit", "missing-apache", "notice-only", "extra", "changed"])
def test_complete_multi_term_instrument_set(change):
    from scripts.ci.release_license_gate import _declaration_matches_text
    directory = Path(__file__).parent / "fixtures" / "license_text"
    texts = [(directory / f"sniffio-instrument-{i}.txt").read_text() for i in range(3)]
    if change == "missing-mit":
        del texts[2]
    elif change == "missing-apache":
        del texts[1]
    elif change == "notice-only":
        texts = texts[:1]
    elif change == "extra":
        texts.append("GPL additional grant")
    elif change == "changed":
        texts[0] += "Commercial use forbidden."
    terms = ["MIT OR Apache-2.0", "MIT License", "Apache Software License"]
    assert _declaration_matches_text(terms, [{"text": t} for t in texts]) is (change == "none")


@pytest.mark.parametrize("change", ["none", "notice-only", "missing-notice", "changed", "grant-changed", "extra", "duplicate"])
def test_complete_apache_attribution_set(change):
    from scripts.ci.release_license_gate import _declaration_matches_text
    directory = Path(__file__).parent / "fixtures" / "license_text"
    texts = [(directory / "sniffio-instrument-1.txt").read_text(),
             (directory / "cyclonedx-notice.txt").read_text()]
    if change == "notice-only":
        texts = texts[1:]
    elif change == "missing-notice":
        texts = texts[:1]
    elif change == "changed":
        texts[1] += "Different attribution."
    elif change == "grant-changed":
        texts[0] = texts[0].replace("perpetual", "temporary")
    elif change == "extra":
        texts.append("GPL additional grant")
    elif change == "duplicate":
        texts.append(texts[1])
    terms = ["Apache-2.0", "Apache Software License"]
    assert _declaration_matches_text(terms, [{"text": t} for t in texts]) is (change in {"none", "missing-notice"})
