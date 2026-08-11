"""Verify distribution metadata needed for licensing and buyer due diligence."""

import ast
import subprocess
import tarfile
import tomli as tomllib
import zipfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]



def test_test_toml_parsers_support_declared_python_floor() -> None:
    """Keep every test module importable on the declared minimum Python."""

    for path in sorted((REPOSITORY_ROOT / "tests").glob("test*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        direct_stdlib_import = any(
            (
                isinstance(node, ast.Import)
                and any(
                    alias.name == "tomllib" and alias.asname is None
                    for alias in node.names
                )
            )
            or (isinstance(node, ast.ImportFrom) and node.module == "tomllib")
            for node in ast.walk(tree)
        )
        assert not direct_stdlib_import, path

    this_module = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imports = {
        (alias.name, alias.asname)
        for node in ast.walk(this_module)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert ("tomli", "tomllib") in imports


def test_tests_workflow_executes_declared_python_floor() -> None:
    """Run the suite on the minimum and current supported interpreters."""

    workflow = (REPOSITORY_ROOT / ".github/workflows/tests.yml").read_text(
        encoding="utf-8"
    )
    assert 'python-version: ["3.10", "3.12"]' in workflow
    assert "python-version: ${{ matrix.python-version }}" in workflow


def packaging_document() -> dict[str, object]:
    """Return the parsed packaging configuration from ``pyproject.toml``."""

    return tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )


def project_metadata() -> dict[str, object]:
    """Return the static PEP 621 project metadata from ``pyproject.toml``."""

    return packaging_document()["project"]


def test_build_backend_is_exact_and_supports_pep639_metadata() -> None:
    """Use one reviewed backend version that understands the license contract."""

    assert packaging_document()["build-system"] == {
        "requires": ["setuptools==83.0.0"],
        "build-backend": "setuptools.build_meta",
    }


def test_distribution_declares_spdx_license_and_includes_license_file() -> None:
    """Bind the built distribution to the repository's exact MIT license text."""

    metadata = project_metadata()

    assert metadata["license"] == "MIT"
    assert metadata["license-files"] == ["LICENSE"]
    license_text = (REPOSITORY_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert license_text.startswith("MIT License\n")
    assert "Copyright (c) 2026 ContextualWisdomLab" in license_text

def test_normal_wheel_and_sdist_carry_pep639_metadata(tmp_path: Path) -> None:
    """Build normal artifacts and inspect their emitted licensing authority."""

    subprocess.run(
        ["uv", "build", "--out-dir", str(tmp_path)],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(tmp_path.glob("*.whl"))
    sdists = list(tmp_path.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1

    expected_license = (REPOSITORY_ROOT / "LICENSE").read_bytes()
    expected_headers = {
        "License-Expression: MIT",
        "License-File: LICENSE",
        *{
            f"Project-URL: {label}, {url}"
            for label, url in project_metadata()["urls"].items()
        },
    }

    with zipfile.ZipFile(wheels[0]) as wheel:
        wheel_names = set(wheel.namelist())
        metadata_name = next(
            name for name in wheel_names if name.endswith(".dist-info/METADATA")
        )
        metadata_headers = set(
            wheel.read(metadata_name).decode("utf-8").splitlines()
        )
        assert expected_headers <= metadata_headers
        license_name = next(
            name
            for name in wheel_names
            if name.endswith(".dist-info/licenses/LICENSE")
        )
        assert wheel.read(license_name) == expected_license

    with tarfile.open(sdists[0], mode="r:gz") as sdist:
        sdist_names = set(sdist.getnames())
        metadata_name = next(
            name for name in sdist_names if name.endswith("/PKG-INFO")
        )
        metadata_file = sdist.extractfile(metadata_name)
        assert metadata_file is not None
        metadata_headers = set(
            metadata_file.read().decode("utf-8").splitlines()
        )
        assert expected_headers <= metadata_headers
        license_name = next(
            name
            for name in sdist_names
            if name.endswith("/LICENSE") and name.count("/") == 1
        )
        license_file = sdist.extractfile(license_name)
        assert license_file is not None
        assert license_file.read() == expected_license

    changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Build and inspect normal wheel and sdist artifacts" in changelog


def test_distribution_exposes_authoritative_project_urls() -> None:
    """Keep package-registry links anchored to the governed repository."""

    assert project_metadata()["urls"] == {
        "Homepage": "https://github.com/ContextualWisdomLab/contextual-orchestrator",
        "Repository": "https://github.com/ContextualWisdomLab/contextual-orchestrator",
        "Issues": "https://github.com/ContextualWisdomLab/contextual-orchestrator/issues",
    }


def test_distribution_description_matches_buyer_facing_product_identity() -> None:
    """Describe the governed product instead of the historical lab prototype."""

    assert project_metadata()["description"] == (
        "Provider-neutral OpenAI-compatible orchestration control plane for "
        "governed routing and multi-agent conduct."
    )


def test_distribution_metadata_change_is_recorded_for_release_review() -> None:
    """Keep the buyer-visible package identity change in release history."""

    changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert (
        "Declare the MIT SPDX license, packaged license file, authoritative project "
        "URLs, and current provider-neutral orchestration-control-plane description "
        "in distribution metadata, and pin the PEP 639-capable setuptools build "
        "backend."
    ) in changelog
