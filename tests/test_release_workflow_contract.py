"""Static contract for the canonical immutable release mechanism.

Pins the structure of `.github/workflows/release.yml` per
docs/planning/adrs/0129-canonical-immutable-release.md: a deliberate,
maintainer-dispatched trigger only; a fail-closed gate that verifies the
released commit is protected main's untampered current tip and that the
requested version matches `pyproject.toml`; a fresh full test-suite run; and
an immutable, never-reused git tag backing a real GitHub Release.

Uses plain text assertions rather than a YAML parser, matching this
repository's existing workflow-contract convention (e.g.
`tests/test_nim_benchmark_workflow_contract.py`) and the Ponytail gate: no
new dependency (PyYAML is not otherwise used anywhere in this repository)
when substring/index assertions already prove the same structure.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/release.yml"


def _workflow_text() -> str:
    """Return the release workflow's raw YAML text."""
    return _WORKFLOW_PATH.read_text(encoding="utf-8")


def test_release_workflow_file_exists() -> None:
    """A first canonical release mechanism must actually be present on disk."""
    assert _WORKFLOW_PATH.exists()


def test_release_is_triggered_only_by_deliberate_manual_dispatch() -> None:
    """Releases are never an automatic side effect of push, PR, or schedule."""
    workflow = _workflow_text()
    trigger_start = workflow.index("\non:\n")
    trigger_end = workflow.index("\npermissions:\n")
    trigger_block = workflow[trigger_start:trigger_end]
    assert "workflow_dispatch:" in trigger_block
    assert "push:" not in trigger_block
    assert "schedule:" not in trigger_block
    assert "pull_request:" not in trigger_block


def test_dispatch_requires_an_explicit_version_input_with_no_default() -> None:
    """A maintainer must type the exact version; nothing is inferred silently."""
    workflow = _workflow_text()
    inputs_start = workflow.index("inputs:")
    permissions_start = workflow.index("\npermissions:\n")
    inputs_block = workflow[inputs_start:permissions_start]
    assert "version:" in inputs_block
    assert "required: true" in inputs_block
    assert "default:" not in inputs_block


def test_release_job_only_runs_against_the_main_branch_ref() -> None:
    """Dispatching against any other branch must not publish a release."""
    workflow = _workflow_text()
    assert "if: github.ref == 'refs/heads/main'" in workflow


def test_write_permission_is_scoped_to_the_release_job_only() -> None:
    """The workflow-default permission stays read-only; only the release job writes."""
    workflow = _workflow_text()
    top_permissions = workflow.index("permissions:\n  contents: read")
    jobs_start = workflow.index("\njobs:\n")
    assert top_permissions < jobs_start
    job_permissions = workflow.index("permissions:\n      contents: write")
    assert job_permissions > jobs_start


def test_gate_verifies_exact_current_main_tip_before_anything_else() -> None:
    """The release must fail closed if a merge landed after dispatch started."""
    workflow = _workflow_text()
    tip_check_index = workflow.index("current, untampered tip")
    tag_step_index = workflow.index("Create the annotated release tag")
    assert tip_check_index < tag_step_index
    assert 'repos/${GITHUB_REPOSITORY}/commits/main" --jq .sha' in workflow
    assert 'if [ "${remote_head}" != "${GITHUB_SHA}" ]' in workflow


def test_gate_verifies_requested_version_matches_pyproject_toml() -> None:
    """A release must never redefine what version an already-merged commit is."""
    workflow = _workflow_text()
    assert 'if [ "${declared}" != "${RELEASE_VERSION}" ]' in workflow
    assert "pyproject.toml" in workflow


def test_gate_refuses_to_republish_or_move_an_existing_tag() -> None:
    """An already-existing tag must block the run instead of being overwritten."""
    workflow = _workflow_text()
    assert 'git rev-parse "refs/tags/v${RELEASE_VERSION}"' in workflow
    assert "repos/${GITHUB_REPOSITORY}/git/ref/tags/v${RELEASE_VERSION}" in workflow


def test_gate_reruns_the_full_test_suite_fresh_before_tagging() -> None:
    """No release ships on a merely-trusted, potentially stale prior test run."""
    workflow = _workflow_text()
    fresh_run_index = workflow.index(
        "uv run --locked --extra api --extra db --extra queue --group dev python -m pytest -q"
    )
    tag_step_index = workflow.index("Create the annotated release tag")
    assert fresh_run_index < tag_step_index


def test_release_notes_are_rendered_from_the_changelog_via_the_tested_helper() -> None:
    """Notes come from the tested extractor, not inline ad hoc text-munging."""
    workflow = _workflow_text()
    assert "python -m scripts.ci.release_notes" in workflow
    assert "--changelog CHANGELOG.md" in workflow
    assert "--output release-notes.md" in workflow


def test_release_tag_is_annotated_and_pushed_before_the_release_is_created() -> None:
    """The immutable tag exists before `gh release create` runs, never after."""
    workflow = _workflow_text()
    tag_index = workflow.index('git tag -a "v${RELEASE_VERSION}"')
    push_index = workflow.index('git push origin "refs/tags/v${RELEASE_VERSION}"')
    publish_index = workflow.index("gh release create")
    assert tag_index < push_index < publish_index


def test_release_notes_file_backs_the_published_release_body() -> None:
    """The GitHub Release body is the rendered notes file, not inline text."""
    workflow = _workflow_text()
    assert "--notes-file release-notes.md" in workflow


def test_sbom_asset_attachment_is_best_effort_and_never_blocks_the_release() -> None:
    """A missing SBOM artifact must warn, not fail, the release."""
    workflow = _workflow_text()
    sbom_step_index = workflow.index("Fetch the CycloneDX SBOM")
    publish_index = workflow.index("Publish the GitHub Release")
    sbom_block = workflow[sbom_step_index:publish_index]
    assert "::warning::" in sbom_block
    assert "gh run download" in sbom_block


def test_concurrency_group_serializes_release_runs() -> None:
    """Two dispatched releases must never race the same tag push."""
    workflow = _workflow_text()
    concurrency_start = workflow.index("\nconcurrency:\n")
    jobs_start = workflow.index("\njobs:\n")
    concurrency_block = workflow[concurrency_start:jobs_start]
    assert "group: release" in concurrency_block
    assert "cancel-in-progress: false" in concurrency_block


def test_pinned_actions_use_full_commit_shas() -> None:
    """Every third-party action reference stays pinned per Scorecard convention."""
    workflow = _workflow_text()
    for line in workflow.splitlines():
        stripped = line.strip()
        if stripped.startswith("uses:"):
            ref = stripped.split("uses:", 1)[1].strip()
            assert "@" in ref
            _, _, pin = ref.partition("@")
            pin = pin.split()[0]
            assert len(pin) == 40, f"unpinned or non-SHA action ref: {ref}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
