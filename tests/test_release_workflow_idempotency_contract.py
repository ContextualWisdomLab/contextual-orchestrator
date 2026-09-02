"""Idempotent-retry and least-privilege contract for the release workflow.

Covers the design that resolves three related Devin/CodeRabbit findings on
`.github/workflows/release.yml`, kept in one file because they share a root
cause -- the tag is pushed before the fallible SBOM/GitHub-Release steps,
so any failure after that push must be safely retryable without ever moving
the tag or double-publishing:

- The tag/release resume-vs-reject branching: an already-existing tag that
  points at this exact commit with no published GitHub Release yet is a
  safe resume; a tag pointing at any other commit, or a tag whose release
  already exists, is rejected rather than silently accepted or overwritten.
- `actions: read` is granted at the `verify` job's scope (needed for the
  best-effort SBOM lookup) and nowhere else.
- The two-job least-privilege split: `verify` (read-only, no persisted git
  credential) executes all repository-controlled code -- the fresh test
  suite and note rendering -- before `publish` (the only job holding
  `contents: write`) ever runs, and `publish`'s first action is an
  authoritative main-tip re-check immediately before it creates anything.

Uses plain text/index assertions on the same raw YAML text convention as
`tests/test_release_workflow_contract.py` (see that file's docstring for the
Ponytail no-new-YAML-dependency rationale) -- but bounded to one job's own
step block via `_job_block`, and to one step's own branch via explicit
ordering assertions, so these prove real operational structure rather than
loose text proximity.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/release.yml"

_JOB_NAMES = ("verify", "publish")


def _workflow_text() -> str:
    """Return the release workflow's raw YAML text."""
    return _WORKFLOW_PATH.read_text(encoding="utf-8")


def _job_block(workflow: str, job_name: str) -> str:
    """Return one top-level job's own YAML text, steps and all.

    Bounded from the job's `  <job_name>:` line to the next known sibling
    job at the same two-space indent, or end of file for the last job.
    """
    start = workflow.index(f"\n  {job_name}:\n")
    later_siblings = [
        workflow.index(f"\n  {sibling}:\n")
        for sibling in _JOB_NAMES
        if sibling != job_name and workflow.index(f"\n  {sibling}:\n") > start
    ]
    end = min(later_siblings) if later_siblings else len(workflow)
    return workflow[start:end]


def _tag_state_step(workflow: str) -> str:
    """Return just the `verify` job's tag-resume-determination step body."""
    verify_block = _job_block(workflow, "verify")
    step_start = verify_block.index(
        "Determine whether the release tag is a fresh publish or a safe resume"
    )
    next_step_start = verify_block.index(
        "Run the full required test suite fresh on this exact commit"
    )
    return verify_block[step_start:next_step_start]


# --- Tag resume-vs-reject branching (Devin finding 3) -----------------------


def test_tag_state_step_exists_with_a_stable_output() -> None:
    """The resume decision is exposed as a step output the `publish` job
    can gate on, not just an internal variable."""
    workflow = _workflow_text()
    verify_block = _job_block(workflow, "verify")
    assert 'id: tag_state' in verify_block
    assert 'echo "tag_resume=false" >> "${GITHUB_OUTPUT}"' in verify_block
    assert 'echo "tag_resume=true" >> "${GITHUB_OUTPUT}"' in verify_block
    assert "outputs:" in verify_block
    assert "tag_resume: ${{ steps.tag_state.outputs.tag_resume }}" in verify_block


def test_absent_tag_is_a_fresh_publish_checked_before_any_reject_branch() -> None:
    """No tag at all must short-circuit straight to `tag_resume=false`,
    before the points-elsewhere/already-published reject logic ever runs
    (that logic requires a tag to exist, so it must come after)."""
    step = _tag_state_step(_workflow_text())
    fresh_index = step.index('echo "tag_resume=false"')
    points_elsewhere_index = step.index("a release tag is never moved onto a different commit")
    already_published_index = step.index("there is nothing left to resume")
    resume_index = step.index('echo "tag_resume=true"')
    assert fresh_index < points_elsewhere_index < already_published_index < resume_index


def test_tag_pointing_at_a_different_commit_is_rejected_not_moved() -> None:
    """A tag that exists but targets a different commit must fail the run
    outright -- a release tag is never moved onto a new commit."""
    step = _tag_state_step(_workflow_text())
    assert '${tag_commit}" != "${GITHUB_SHA}' in step
    mismatch_index = step.index('${tag_commit}" != "${GITHUB_SHA}')
    # The very next non-blank statement after the mismatch check must exit
    # nonzero -- reject, don't silently continue past a moved tag.
    following = step[mismatch_index : mismatch_index + 400]
    assert "::error::" in following
    assert "exit 1" in following


def test_tag_matching_commit_with_existing_release_is_rejected_as_nothing_to_resume() -> None:
    """A tag at the right commit whose GitHub Release already exists must
    also reject -- retries are for incomplete publications, not to
    re-publish a release that already exists."""
    step = _tag_state_step(_workflow_text())
    assert 'gh release view "v${RELEASE_VERSION}"' in step
    release_view_index = step.index('gh release view "v${RELEASE_VERSION}"')
    following = step[release_view_index : release_view_index + 400]
    assert "::error::" in following
    assert "exit 1" in following
    assert "already has a published GitHub Release" in following


def test_tag_matching_commit_with_no_release_yet_resumes_without_retagging() -> None:
    """Only the narrow safe case -- same commit, no release published yet --
    sets `tag_resume=true`, and this must be the last branch reached (after
    both reject checks have already passed)."""
    step = _tag_state_step(_workflow_text())
    resume_notice_index = step.index("resuming publication instead of re-tagging")
    resume_output_index = step.index('echo "tag_resume=true"')
    release_view_index = step.index('gh release view "v${RELEASE_VERSION}"')
    assert release_view_index < resume_notice_index < resume_output_index


def test_publish_job_skips_tag_creation_only_when_resuming() -> None:
    """`publish` must gate the actual `git tag`/`git push` step on the
    resume flag computed by `verify` -- not recompute or ignore it."""
    workflow = _workflow_text()
    publish_block = _job_block(workflow, "publish")
    assert "TAG_RESUME: ${{ needs.verify.outputs.tag_resume }}" in publish_block
    tag_step_index = publish_block.index("Create the annotated release tag")
    following_line_end = publish_block.index("\n", tag_step_index)
    if_line = publish_block[tag_step_index:publish_block.index("\n", following_line_end + 1)]
    assert "if: env.TAG_RESUME != 'true'" in if_line


# --- `actions: read` scoping (Devin finding 2) -------------------------------


def test_actions_read_is_granted_only_on_the_verify_job() -> None:
    """`actions: read` (needed for `gh run list`/`gh run download`) belongs
    on `verify`, which performs the SBOM lookup, and nowhere else -- the
    write-scoped `publish` job never needs Actions API access."""
    workflow = _workflow_text()
    verify_block = _job_block(workflow, "verify")
    publish_block = _job_block(workflow, "publish")
    assert "actions: read" in verify_block
    assert "actions: read" not in publish_block


def test_sbom_step_is_the_one_step_needing_actions_read() -> None:
    """The permission and the step that consumes it live in the same job."""
    workflow = _workflow_text()
    verify_block = _job_block(workflow, "verify")
    assert "gh run list" in verify_block
    assert "gh run download" in verify_block


# --- Two-job least-privilege split (CodeRabbit CWE-269 hardening) -----------


def test_publish_job_depends_on_verify_completing_first() -> None:
    """`publish` must not run until `verify` (which runs the fresh test
    suite and renders notes) has fully succeeded."""
    workflow = _workflow_text()
    publish_block = _job_block(workflow, "publish")
    assert "needs: verify" in publish_block


def test_only_publish_job_holds_write_permission_and_persisted_credentials() -> None:
    """The write-scoped token and a persisted git credential exist only in
    `publish`; `verify` -- which runs repository-controlled test code --
    never holds either."""
    workflow = _workflow_text()
    verify_block = _job_block(workflow, "verify")
    publish_block = _job_block(workflow, "publish")
    assert "contents: write" in publish_block
    assert "contents: write" not in verify_block
    assert "persist-credentials: true" in publish_block
    assert "persist-credentials: false" in verify_block


def test_publish_jobs_first_step_is_checkout_and_second_is_the_final_tip_check() -> None:
    """The re-verification must be the very first thing `publish` does
    after checking out -- nothing fallible runs before it."""
    workflow = _workflow_text()
    publish_block = _job_block(workflow, "publish")
    step_names = [
        line.split("- name:", 1)[1].strip()
        for line in publish_block.splitlines()
        if line.strip().startswith("- name:")
    ]
    assert step_names[0] == "Checkout protected main"
    assert step_names[1] == "Re-verify protected main has not advanced since verification started"


def test_release_artifacts_flow_from_verify_to_publish_via_upload_download() -> None:
    """Notes/SBOM produced in the credential-less `verify` job reach
    `publish` through an artifact hand-off, not a shared filesystem or a
    second independent render (which could drift from what was tested)."""
    workflow = _workflow_text()
    verify_block = _job_block(workflow, "verify")
    publish_block = _job_block(workflow, "publish")
    assert "actions/upload-artifact@" in verify_block
    assert "name: release-publish-inputs" in verify_block
    assert "actions/download-artifact@" in publish_block
    assert "name: release-publish-inputs" in publish_block


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
