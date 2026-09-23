"""The built distribution must declare the licence the repository carries.

A release SBOM can only report what the distribution's own metadata says. This
project shipped a MIT `LICENSE` file while declaring no licence at all, so its
own component appeared in the CycloneDX SBOM with no licence and the release
licence gate classified it as undecidable -- correctly, since undeclared is not
permission. These tests pin the metadata rather than the gate's reaction to it.

Metadata is generated through the declared build backend's
`prepare_metadata_for_build_wheel` hook, which writes a `.dist-info` directory
without compiling anything, so this stays a metadata check and not a build.
"""

from __future__ import annotations

import email
import sys
import tomllib
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    with open(REPOSITORY_ROOT / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)


def test_license_declaration_matches_the_repository_license_file() -> None:
    project = _pyproject()["project"]
    license_text = (REPOSITORY_ROOT / "LICENSE").read_text(encoding="utf-8")

    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]
    assert license_text.startswith("MIT License")


def test_build_backend_floor_supports_the_license_expression() -> None:
    """PEP 639 metadata is only emitted from setuptools 77 onwards."""
    build_system = _pyproject()["build-system"]

    assert build_system["build-backend"] == "setuptools.build_meta"
    assert any(requirement.replace(" ", "") == "setuptools>=77" for requirement in build_system["requires"])


def test_generated_metadata_declares_the_license(tmp_path) -> None:
    setuptools = pytest.importorskip("setuptools")
    if tuple(int(part) for part in setuptools.__version__.split(".")[:1]) < (77,):
        pytest.skip(f"setuptools {setuptools.__version__} predates PEP 639 support")
    from setuptools import build_meta

    previous = Path.cwd()
    sys.path.insert(0, str(REPOSITORY_ROOT))
    try:
        import os

        os.chdir(REPOSITORY_ROOT)
        dist_info = build_meta.prepare_metadata_for_build_wheel(str(tmp_path))
    finally:
        os.chdir(previous)
        sys.path.remove(str(REPOSITORY_ROOT))

    metadata = email.message_from_string((tmp_path / dist_info / "METADATA").read_text(encoding="utf-8"))

    assert metadata.get("License-Expression") == "MIT"
    assert "LICENSE" in " ".join(metadata.get_all("License-File") or [])
