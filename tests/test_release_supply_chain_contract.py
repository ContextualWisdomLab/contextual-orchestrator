"""Release tag identity and mandatory SBOM supply-chain contract."""

from pathlib import Path
import os
import subprocess
import textwrap

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPOSITORY_ROOT / ".github/workflows/release.yml"


def _workflow_text() -> str:
    """Return the canonical release workflow text."""
    return WORKFLOW.read_text(encoding="utf-8")


def test_release_tag_lookup_uses_exact_tags_namespace() -> None:
    """A branch named like a release version must never impersonate a tag."""
    workflow = _workflow_text()
    assert 'git/ref/tags/v${RELEASE_VERSION}' in workflow
    assert 'commits/v${RELEASE_VERSION}' not in workflow


def test_release_requires_sbom_before_publication() -> None:
    """A canonical release cannot proceed when exact-commit SBOM evidence is absent."""
    workflow = _workflow_text()
    fetch_start = workflow.index("Fetch the required CycloneDX SBOM for this commit")
    publish_start = workflow.index("  publish:", fetch_start)
    fetch_block = workflow[fetch_start:publish_start]

    assert "best-effort" not in fetch_block
    assert "publishing without" not in fetch_block
    assert "exit 1" in fetch_block
    assert "if-no-files-found: error" in fetch_block


def test_release_builds_wheel_without_system_setuptools() -> None:
    """A clean verifier must install its build backend in isolation."""
    workflow = _workflow_text()
    build = workflow.split("      - name: Build the installable package for this exact commit\n", 1)[1]
    build = build.split("\n      - name:", 1)[0]
    assert "uv build --wheel --python 3.12 --out-dir dist" in build
    assert 'SOURCE_DATE_EPOCH="$(git show -s --format=%ct "${TARGET_SHA}")"' in build
    assert "export SOURCE_DATE_EPOCH" in build
    assert 'uv build --wheel --python 3.12 --out-dir "${RUNNER_TEMP}/release-rebuild"' in build
    assert 'cmp "${wheel}" "${RUNNER_TEMP}/release-rebuild/${wheel##*/}"' in build
    assert "uv pip install --no-deps --python 3.12 --target" in build
    assert "--no-build-isolation" not in build
    assert "importlib.metadata.distributions(path=[str(site)])" in build


def test_sbom_asset_attachment_is_fail_closed() -> None:
    """A published canonical release must not report success with its SBOM missing."""
    workflow = _workflow_text()
    attach_start = workflow.index("Attach required release SBOM")
    attach_block = workflow[attach_start:]

    assert "best-effort" not in attach_block
    assert "release is published without it" not in attach_block
    assert 'gh release upload "v${RELEASE_VERSION}"' in attach_block
    assert "exit 1" in attach_block


@pytest.mark.parametrize("scenario,success", [
    ("same", True), ("different", False), ("absent", True),
    ("download_failure", False), ("upload_failure", False),
    ("download_missing", False), ("download_empty", False),
])
def test_sbom_attachment_checks_remote_bytes(tmp_path: Path, scenario: str, success: bool) -> None:
    """Execute the real attachment step; name equality cannot prove immutability."""
    block = _workflow_text().split("      - name: Attach required release SBOM\n", 1)[1]
    run_body = block.split("        run: |\n", 1)[1]
    # The attach step is followed by later publish steps; execute only this run block.
    if "\n      - name:" in run_body:
        run_body = run_body.split("\n      - name:", 1)[0]
    script = textwrap.dedent(run_body)
    evidence_dir = tmp_path / "sbom-download"
    evidence_dir.mkdir()
    temporary_dir = tmp_path / "temporary"
    temporary_dir.mkdir()
    (evidence_dir / "cyclonedx-sbom.json").write_text('{"serialNumber":"expected"}')
    stub = tmp_path / "gh"
    stub.write_text('''#!/bin/bash
set -eu
case "$2" in
  view)
    if [ "$SCENARIO" != absent ] && [ "$SCENARIO" != upload_failure ] || [ -f uploaded ]; then
      echo cyclonedx-sbom.json
    fi ;;
  upload)
    [ "$SCENARIO" != upload_failure ] || exit 1
    touch uploaded ;;
  download)
    [ "$SCENARIO" != download_failure ] || exit 1
    while [ "$1" != --dir ]; do shift; done
    mkdir -p "$2"
    [ "$SCENARIO" != download_missing ] || exit 0
    if [ "$SCENARIO" = download_empty ]; then
      touch "$2/cyclonedx-sbom.json"
      exit 0
    fi
    if [ "$SCENARIO" = different ]; then
      echo different > "$2/cyclonedx-sbom.json"
    else
      cp sbom-download/cyclonedx-sbom.json "$2/cyclonedx-sbom.json"
    fi ;;
  *) exit 99 ;;
esac
''')
    stub.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
             "TMPDIR": str(temporary_dir),
             "SCENARIO": scenario, "RELEASE_VERSION": "0.2.0",
             "GITHUB_REPOSITORY": "example/test"},
    )
    assert (result.returncode == 0) is success, result.stdout + result.stderr
    assert (tmp_path / "uploaded").exists() is (scenario == "absent")
