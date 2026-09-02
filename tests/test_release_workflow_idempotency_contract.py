"""Idempotent-retry and least-privilege contract for the release workflow.

Covers the design that resolves four related Devin/CodeRabbit findings on
`.github/workflows/release.yml`, kept in one file because they share a root
cause -- the tag (and, now, the Release object itself) is created before the
fallible SBOM-asset step, so any failure after that must be safely
retryable without ever moving the tag or double-publishing:

- The tag resume-vs-reject branching: an already-existing tag that points
  at this exact commit is a safe resume; a tag pointing at any other commit
  is rejected rather than silently accepted or overwritten.
- The Release resume-vs-create branching (`release_resume`, a Devin
  follow-up finding distinct from the tag one above): a GitHub Release that
  already exists for this exact commit is *also* a safe resume -- `gh
  release create` can publish the Release object and then fail partway
  through uploading its assets, so "the Release already exists" must not be
  treated as "nothing left to do." `publish` always attempts the
  best-effort SBOM asset attach afterward, whether the Release was just
  created or already existed.
- `actions: read` is granted at the `verify` job's scope (needed for the
  best-effort SBOM lookup) and nowhere else.
- The two-job least-privilege split: `verify` (read-only, no persisted git
  credential) executes all repository-controlled code -- the fresh test
  suite and note rendering -- before `publish` (the only job holding
  `contents: write`) ever runs, and `publish`'s first actions are an
  authoritative main-tip re-check and a checks-green re-check, immediately
  before it creates anything.

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


# --- Tag/Release resume-vs-reject branching (Devin findings 3 and the
# --- follow-up "Failed asset upload strands releases") ----------------------


def test_tag_state_step_exists_with_a_stable_output() -> None:
    """The resume decisions are exposed as step outputs the `publish` job
    can gate on, not just internal variables. Two separate flags -- whether
    the tag itself is safe to skip re-creating, and whether the GitHub
    Release object is safe to skip re-creating -- because a Devin follow-up
    finding showed those are not the same question (see the
    `release_resume`-specific tests below)."""
    workflow = _workflow_text()
    verify_block = _job_block(workflow, "verify")
    assert 'id: tag_state' in verify_block
    assert 'echo "tag_resume=false" >> "${GITHUB_OUTPUT}"' in verify_block
    assert 'echo "tag_resume=true" >> "${GITHUB_OUTPUT}"' in verify_block
    assert 'echo "release_resume=false" >> "${GITHUB_OUTPUT}"' in verify_block
    assert 'echo "release_resume=true" >> "${GITHUB_OUTPUT}"' in verify_block
    assert "outputs:" in verify_block
    assert "tag_resume: ${{ steps.tag_state.outputs.tag_resume }}" in verify_block
    assert "release_resume: ${{ steps.tag_state.outputs.release_resume }}" in verify_block


def test_absent_tag_is_a_fresh_publish_checked_before_any_reject_branch() -> None:
    """No tag at all must short-circuit straight to `tag_resume=false`,
    before the points-elsewhere reject branch or the tag_resume=true branch
    (which requires a tag to exist) ever run."""
    step = _tag_state_step(_workflow_text())
    fresh_index = step.index('echo "tag_resume=false"')
    points_elsewhere_index = step.index("a release tag is never moved onto a different commit")
    tag_resume_true_index = step.index('echo "tag_resume=true"')
    assert fresh_index < points_elsewhere_index < tag_resume_true_index


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


def test_tag_matching_commit_sets_tag_resume_before_branching_on_release_existence() -> None:
    """Once the tag is confirmed to point at this exact commit, `tag_resume`
    is set unconditionally -- only whether the GitHub Release itself
    already exists (`release_resume`) still needs its own branch."""
    step = _tag_state_step(_workflow_text())
    mismatch_index = step.index('${tag_commit}" != "${GITHUB_SHA}')
    tag_resume_true_index = step.index('echo "tag_resume=true"')
    release_view_index = step.index('gh release view "v${RELEASE_VERSION}"')
    assert mismatch_index < tag_resume_true_index < release_view_index


def test_tag_matching_commit_with_existing_release_resumes_to_attach_missing_assets() -> None:
    """A tag at the right commit whose GitHub Release already exists is a
    safe resume too, not a reject: `gh release create` can publish the
    Release object and then fail partway through uploading assets, so the
    tag and the Release can both already exist while the SBOM asset is
    still missing. The earlier "nothing left to resume" rejection stranded
    that release forever (Devin's follow-up finding) -- `publish` must
    still get a chance to attempt the best-effort asset attach."""
    step = _tag_state_step(_workflow_text())
    assert 'gh release view "v${RELEASE_VERSION}"' in step
    release_view_index = step.index('gh release view "v${RELEASE_VERSION}"')
    # Bounded to the "release already exists" branch itself (up to its
    # `else`), not an arbitrary character count -- the branch's own
    # explanatory comment is long enough to overflow a fixed window.
    else_index = step.index("\n          else\n", release_view_index)
    branch = step[release_view_index:else_index]
    assert "::error::" not in branch
    assert "exit 1" not in branch
    assert 'echo "release_resume=true" >> "${GITHUB_OUTPUT}"' in branch


def test_tag_matching_commit_with_no_release_yet_resumes_without_retagging() -> None:
    """The narrow case -- same commit, no release published yet -- sets
    `release_resume=false` (still resuming the tag, but the Release itself
    must still be created), and this branch is reached only after the
    release-exists check has already run."""
    step = _tag_state_step(_workflow_text())
    release_view_index = step.index('gh release view "v${RELEASE_VERSION}"')
    resume_notice_index = step.index("resuming publication instead of re-tagging", release_view_index)
    resume_output_index = step.index('echo "release_resume=false" >> "${GITHUB_OUTPUT}"', release_view_index)
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


def test_publish_job_only_creates_the_release_when_it_does_not_already_exist() -> None:
    """`publish` must gate `gh release create` on `release_resume` -- when a
    Release already exists for this commit, creating it again would fail
    outright rather than resuming the asset attach."""
    workflow = _workflow_text()
    publish_block = _job_block(workflow, "publish")
    assert "RELEASE_RESUME: ${{ needs.verify.outputs.release_resume }}" in publish_block
    create_step_index = publish_block.index("Create the GitHub Release")
    following_line_end = publish_block.index("\n", create_step_index)
    if_line = publish_block[create_step_index:publish_block.index("\n", following_line_end + 1)]
    assert "if: env.RELEASE_RESUME != 'true'" in if_line


def test_release_asset_attach_always_runs_and_is_best_effort() -> None:
    """Whether the Release was just created fresh or already existed on a
    resumed run, attaching the SBOM asset must still be attempted -- and a
    failed attach must never fail the whole run, matching this workflow's
    established SBOM best-effort convention (Devin's follow-up finding: an
    asset upload failing after `gh release create` already succeeded must
    be retryable, not stranded)."""
    workflow = _workflow_text()
    publish_block = _job_block(workflow, "publish")
    create_step_index = publish_block.index("Create the GitHub Release")
    attach_step_index = publish_block.index("Attach any still-missing release assets")
    assert create_step_index < attach_step_index

    attach_step = publish_block[attach_step_index:]
    step_header = attach_step[: attach_step.index("run:")]
    # The attach step itself carries no `if:` gate -- it must run whether
    # `Create the GitHub Release` ran or was skipped as already-resumed.
    assert "if:" not in step_header
    assert "set -euo pipefail" not in attach_step, (
        "the attach step must not abort-on-error via -e; a failed upload "
        "needs its own explicit, non-fatal handling instead"
    )
    assert "if ! gh release upload" in attach_step
    assert "::warning::" in attach_step
    assert "--clobber" in attach_step


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
