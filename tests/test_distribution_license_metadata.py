"""The built distribution must declare the licence the repository carries.

A release SBOM can only report what the distribution's own metadata says. This
project shipped a MIT `LICENSE` file while declaring no licence at all, so its
own component appeared in the CycloneDX SBOM with no licence and the release
licence gate classified it as undecidable -- correctly, since undeclared is not
permission. These tests pin the metadata rather than the gate's reaction to it.

Metadata is generated through the declared build backend's
`prepare_metadata_for_build_wheel` hook, which writes a `.dist-info` directory
without compiling anything, so this stays a metadata check and not a build.

Two limits are deliberate and recorded rather than papered over. The backend
check fails instead of skipping when setuptools predates PEP 639, because a
skipped licence check reported as a pass is exactly the hole this file exists
to close. And the `LICENSE` assertion matches the MIT header, not the full
text: it catches a file replaced by a different licence, not a doctored clause
inside an otherwise MIT-looking file.
"""

from __future__ import annotations

import email
import sys
import tomllib
from pathlib import Path

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
    import setuptools  # a build backend this project declares, never optional here
    from setuptools import build_meta

    major = int(setuptools.__version__.split(".")[0])
    assert major >= 77, (
        f"setuptools {setuptools.__version__} predates PEP 639, so this environment cannot emit the "
        "licence expression. Failing rather than skipping: a skipped licence check must never be "
        "counted as a passing one."
    )

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
