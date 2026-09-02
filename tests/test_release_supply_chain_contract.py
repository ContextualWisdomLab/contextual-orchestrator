"""Release tag identity and mandatory SBOM supply-chain contract."""

from pathlib import Path


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
    fetch_start = workflow.index("Fetch the CycloneDX SBOM for this commit")
    publish_start = workflow.index("  publish:", fetch_start)
    fetch_block = workflow[fetch_start:publish_start]

    assert "best-effort" not in fetch_block
    assert "publishing without" not in fetch_block
    assert "exit 1" in fetch_block
    assert "if-no-files-found: error" in fetch_block


def test_sbom_asset_attachment_is_fail_closed() -> None:
    """A published canonical release must not report success with its SBOM missing."""
    workflow = _workflow_text()
    attach_start = workflow.index("Attach any still-missing release assets")
    attach_block = workflow[attach_start:]

    assert "best-effort" not in attach_block
    assert "release is published without it" not in attach_block
    assert 'gh release upload "v${RELEASE_VERSION}"' in attach_block
    assert "exit 1" in attach_block
