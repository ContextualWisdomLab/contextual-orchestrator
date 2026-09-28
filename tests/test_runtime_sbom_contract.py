"""The release SBOM must describe the pinned runtime, not the CI tool environment."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts/ci/verify_runtime_sbom.py"


def _run(
    tmp_path: Path, *, components: list[dict], version: str = "0.2.0",
    rooted: bool = True, partial_root: bool = False,
) -> subprocess.CompletedProcess[str]:
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "\n".join([
            "alpha==1.0 \\",
            "    --hash=sha256:" + "a" * 64,
            "beta-core==2.0 \\",
            "    --hash=sha256:" + "b" * 64,
        ]) + "\n",
        encoding="utf-8",
    )
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname = "contextual-orchestrator"\nversion = "0.2.0"\n', encoding="utf-8")
    sbom = tmp_path / "sbom.json"
    components = [
        {**component, "bom-ref": f"{component['name']}=={component['version']}"}
        for component in components
    ]
    dependencies = [
        {"ref": component["bom-ref"], "dependsOn": []}
        for component in components
    ]
    root_children = [component["bom-ref"] for component in components] if rooted else []
    dependencies.append({
        "ref": "root-component",
        "dependsOn": root_children[:1] if partial_root else root_children,
    })
    sbom.write_text(json.dumps({
        "bomFormat": "CycloneDX",
        "metadata": {"component": {
            "bom-ref": "root-component", "name": "contextual-orchestrator", "version": version,
        }},
        "components": components,
        "dependencies": dependencies,
    }), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(VERIFY), str(lock), str(project), str(sbom)],
        text=True, capture_output=True, check=False,
    )


def test_runtime_sbom_exactly_matches_pins(tmp_path: Path) -> None:
    result = _run(tmp_path, components=[
        {"name": "alpha", "version": "1.0"},
        {"name": "beta_core", "version": "2.0"},
    ])
    assert result.returncode == 0, result.stderr


def test_runtime_sbom_rejects_missing_or_ci_only_packages(tmp_path: Path) -> None:
    for components in (
        [{"name": "alpha", "version": "1.0"}],
        [
            {"name": "alpha", "version": "1.0"},
            {"name": "beta-core", "version": "2.0"},
            {"name": "pip-audit", "version": "9.0"},
        ],
    ):
        result = _run(tmp_path, components=components)
        assert result.returncode != 0


def test_runtime_sbom_rejects_wrong_project_version(tmp_path: Path) -> None:
    result = _run(tmp_path, components=[
        {"name": "alpha", "version": "1.0"},
        {"name": "beta-core", "version": "2.0"},
    ], version="0.1.0")
    assert result.returncode != 0


def test_runtime_sbom_rejects_incomplete_root_graph(tmp_path: Path) -> None:
    result = _run(tmp_path, components=[
        {"name": "alpha", "version": "1.0"},
        {"name": "beta-core", "version": "2.0"},
    ], rooted=False)
    assert result.returncode != 0
    result = _run(tmp_path, components=[
        {"name": "alpha", "version": "1.0"},
        {"name": "beta-core", "version": "2.0"},
    ], partial_root=True)
    assert result.returncode != 0


def test_workflows_generate_and_verify_runtime_lock_sbom() -> None:
    security = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "python -m venv --without-pip" in security
    assert "python -m pip install --no-deps --require-hashes --target" in security
    assert "cyclonedx-py environment \"${runtime_python}\" --pyproject pyproject.toml" in security
    assert "python scripts/ci/verify_runtime_sbom.py requirements.lock pyproject.toml cyclonedx-sbom.json" in security
    assert "python scripts/ci/verify_runtime_sbom.py requirements.lock pyproject.toml \"${sbom_file}\"" in release
