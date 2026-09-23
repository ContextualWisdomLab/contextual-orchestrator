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

from scripts.ci.release_license_gate import classify_sbom_components, main  # noqa: E402


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


def test_native_manifest_without_sbom_coverage_fails_closed(tmp_path) -> None:
    """Rust and npm manifests ship in the image, so the SBOM must cover them."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\nversion = "0.0.1"\ndependencies = []\n', encoding="utf-8")
    (tmp_path / "rust").mkdir()
    (tmp_path / "rust" / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    sbom = _sbom(_component("python_only_library", "1.0", license_id="MIT"))

    assert main(["--sbom", _write(tmp_path, sbom), "--pyproject", str(pyproject),
                 "--repository-root", str(tmp_path)]) == 1
