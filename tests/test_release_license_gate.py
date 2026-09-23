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

    assert {row["name"] for row in groups["unknown"]} == {"undeclared_library", "placeholder_library"}
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
