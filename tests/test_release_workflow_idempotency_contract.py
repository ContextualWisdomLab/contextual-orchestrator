"""Idempotent-retry and least-privilege contract for the release workflow.

Covers the design that resolves five related Devin/CodeRabbit findings on
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
- Confirmed-absence vs transient-failure classification for both lookups
  (Devin's later finding, "API failures block release recovery"): a failed
  tag lookup or `gh release view` call is *not* automatically "absent" --
  only a confirmed HTTP 404 (tag) or "release not found" (Release) means
  that; any other failure (rate limit, auth, network blip, a GitHub 5xx)
  fails the step closed instead of risking a wrong fresh-create attempt
  against unconfirmed state. See the real bash+stub-`gh` simulation near
  the end of this file for end-to-end coverage beyond text assertions.
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
loose text proximity. The confirmed-absence-vs-transient-failure tests near
the end of this file go further: they execute the tag_state step's actual,
unmodified script under bash against a stubbed `gh`, the same
real-execution technique `tests/test_release_workflow_contract.py` uses for
the checks-green gate.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/release.yml"

_JOB_NAMES = ("verify", "publish")

# Fixed, deterministic values for the hand-simulation tests near the end of
# this file -- arbitrary, just stable and easy to eyeball in a failure.
_SIM_GITHUB_REPOSITORY = "ContextualWisdomLab/contextual-orchestrator"
_SIM_RELEASE_VERSION = "0.2.0"
_SIM_GITHUB_SHA = "cf69dc39457829c351277aad8096c24115d3991c"


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


def test_tag_lookup_confirmed_404_is_a_fresh_publish_without_error() -> None:
    """Devin finding ("API failures block release recovery"): only a
    confirmed HTTP 404 from the tag lookup means "tag absent" -- that
    branch must resume as a clean fresh publish, no error, no exit 1,
    distinct from the non-404 fail-closed branch tested right below."""
    step = _tag_state_step(_workflow_text())
    lookup_index = step.index('if ! tag_lookup_output=')
    confirmed_404_index = step.index('grep -q "HTTP 404"', lookup_index)
    inner_fi_index = step.index('\n            fi\n', confirmed_404_index)
    confirmed_404_branch = step[confirmed_404_index:inner_fi_index]
    assert "::error::" not in confirmed_404_branch
    assert 'echo "tag_resume=false" >> "${GITHUB_OUTPUT}"' in confirmed_404_branch
    assert 'echo "release_resume=false" >> "${GITHUB_OUTPUT}"' in confirmed_404_branch
    assert "exit 0" in confirmed_404_branch


def test_tag_lookup_non_404_error_fails_closed_not_treated_as_absent() -> None:
    """Devin finding ("API failures block release recovery"): a transient
    rate-limit, auth, network, or 5xx failure from the tag lookup must
    never be silently treated as 'tag absent' -- it must fail this step
    closed (distinct exit 1, after the confirmed-404 short-circuit already
    had its chance to `exit 0` first) so a later retry can resolve cleanly
    instead of compounding a wrong assumption."""
    step = _tag_state_step(_workflow_text())
    lookup_index = step.index('if ! tag_lookup_output=')
    confirmed_404_fi_index = step.index('\n            fi\n', lookup_index)
    outer_fi_index = step.index('\n          fi\n', confirmed_404_fi_index)
    fail_closed_branch = step[confirmed_404_fi_index:outer_fi_index]
    assert "::error::" in fail_closed_branch
    assert "exit 1" in fail_closed_branch
    assert "NOT confirmed" in fail_closed_branch
    assert "tag_resume=" not in fail_closed_branch
    assert "release_resume=" not in fail_closed_branch


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
    still get a chance to attempt the best-effort asset attach.

    `gh release view` succeeding (exit 0) is now the *outer* `else` of a
    three-way branch -- see the two tests below for the other two arms
    (confirmed absent, and Devin's later "API failures block release
    recovery" finding: any other lookup failure fails closed instead of
    being treated as absence). Bounded to that outer branch specifically
    via its 10-space indentation, which the branch's own inner if/else
    (12-space indented) cannot be mistaken for."""
    step = _tag_state_step(_workflow_text())
    assert 'gh release view "v${RELEASE_VERSION}"' in step
    release_view_index = step.index('gh release view "v${RELEASE_VERSION}"')
    outer_else_index = step.index("\n          else\n", release_view_index)
    outer_fi_index = step.index("\n          fi\n", outer_else_index)
    branch = step[outer_else_index:outer_fi_index]
    assert "::error::" not in branch
    assert "exit 1" not in branch
    assert 'echo "release_resume=true" >> "${GITHUB_OUTPUT}"' in branch


def test_release_lookup_confirmed_absent_resumes_cleanly_without_error() -> None:
    """The confirmed-absent inner arm (a genuine 'release not found', or
    its raw HTTP-404 rendering as a defensive fallback) must resume
    publication cleanly -- no error, no exit 1 -- and must be distinct from
    the non-404 fail-closed arm right next to it (Devin finding: "API
    failures block release recovery")."""
    step = _tag_state_step(_workflow_text())
    release_view_index = step.index('gh release view "v${RELEASE_VERSION}"')
    inner_else_index = step.index("\n            else\n", release_view_index)
    confirmed_absent_branch = step[release_view_index:inner_else_index]
    assert 'grep -qiE "release not found|HTTP 404"' in confirmed_absent_branch
    assert "::error::" not in confirmed_absent_branch
    assert "exit 1" not in confirmed_absent_branch
    assert 'echo "release_resume=false" >> "${GITHUB_OUTPUT}"' in confirmed_absent_branch


def test_release_lookup_non_404_error_fails_closed_not_treated_as_absent() -> None:
    """Devin finding ("API failures block release recovery"): a transient
    rate-limit, auth, network, or 5xx failure from `gh release view` must
    never be silently treated as 'Release absent' -- only a confirmed
    absence may resume; anything else fails this step closed so a later
    retry can resolve cleanly instead of compounding a wrong assumption."""
    step = _tag_state_step(_workflow_text())
    release_view_index = step.index('gh release view "v${RELEASE_VERSION}"')
    inner_else_index = step.index("\n            else\n", release_view_index)
    inner_fi_index = step.index("\n            fi\n", inner_else_index)
    fail_closed_branch = step[inner_else_index:inner_fi_index]
    assert "::error::" in fail_closed_branch
    assert "exit 1" in fail_closed_branch
    assert "NOT confirmed" in fail_closed_branch
    assert "release_resume=false" not in fail_closed_branch
    assert "release_resume=true" not in fail_closed_branch


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


# --- Confirmed-absence vs transient-failure real-execution simulation
# --- (Devin finding: "API failures block release recovery") ----------------
#
# The tests above prove the *branch structure* of the tag_state step's real
# YAML text. These go further: they execute that exact, unmodified script
# (never a hand-copied stand-in that could silently drift from it) under
# bash, against a stub `gh` selected by GH_STUB_MODE, covering every branch
# end-to-end -- exit code and the actual GITHUB_OUTPUT lines written -- the
# same real-execution technique tests/test_release_workflow_contract.py
# uses for the checks-green gate.


def _tag_state_script(workflow: str) -> str:
    """Return the tag_state step's real `run: |` script body, dedented.

    Terminates at the first line that is not blank and does not carry this
    workflow's fixed 10-space step-script indentation, mirroring YAML's own
    block-scalar boundary rule (see the analogous helper's longer rationale
    in tests/test_release_workflow_contract.py).
    """
    step = _tag_state_step(workflow)
    marker = "run: |\n"
    body = step[step.index(marker) + len(marker) :]
    lines: list[str] = []
    for line in body.splitlines():
        if line.strip() == "":
            lines.append("")
            continue
        if not line.startswith(" " * 10):
            break
        lines.append(line[10:])
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


_STUB_GH_TAG_RELEASE_LOOKUP = """#!/usr/bin/env bash
# Stub gh CLI for hand-simulating the tag_state step's two lookups against
# deliberately-crafted success/confirmed-absence/transient-failure cases,
# selected via GH_STUB_TAG_MODE and GH_STUB_RELEASE_MODE.
tag_mode="${GH_STUB_TAG_MODE:-}"
release_mode="${GH_STUB_RELEASE_MODE:-}"

if [ "$1" = "api" ]; then
  case "${tag_mode}" in
    tag_confirmed_404)
      echo "gh: No commit found for SHA: v${RELEASE_VERSION} (HTTP 404)" >&2
      exit 1
      ;;
    tag_rate_limited)
      echo "gh: API rate limit exceeded for user ID 123. (HTTP 403)" >&2
      exit 1
      ;;
    tag_network_error)
      echo 'gh: Post "https://api.github.com/graphql": dial tcp: lookup api.github.com: no such host' >&2
      exit 1
      ;;
    tag_exists)
      if printf '%s\\n' "$*" | grep -q -- '--jq'; then
        echo "${SIM_GITHUB_SHA}"
      else
        echo "{\\"sha\\":\\"${SIM_GITHUB_SHA}\\"}"
      fi
      exit 0
      ;;
    *) echo "unhandled stub gh api tag mode: ${tag_mode}" >&2; exit 97 ;;
  esac
elif [ "$1" = "release" ] && [ "$2" = "view" ]; then
  case "${release_mode}" in
    release_confirmed_absent)
      echo "release not found" >&2
      exit 1
      ;;
    release_rate_limited)
      echo "gh: API rate limit exceeded for user ID 123. (HTTP 403)" >&2
      exit 1
      ;;
    release_exists)
      echo "title: v${RELEASE_VERSION}"
      exit 0
      ;;
    *) echo "unhandled stub gh release view mode: ${release_mode}" >&2; exit 97 ;;
  esac
else
  echo "unhandled stub gh invocation: $*" >&2
  exit 98
fi
"""


def _run_tag_state_script(
    tmp_path: Path, script: str, *, tag_mode: str, release_mode: str = ""
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Execute the real tag_state script against the stub gh above.

    Returns the completed process plus the `GITHUB_OUTPUT` lines actually
    written, parsed into a dict (empty if the step exited before writing
    any, e.g. the fail-closed branches).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_stub = bin_dir / "gh"
    gh_stub.write_text(_STUB_GH_TAG_RELEASE_LOOKUP, encoding="utf-8")
    gh_stub.chmod(0o755)

    script_path = tmp_path / "tag-state.sh"
    script_path.write_text(script, encoding="utf-8")
    output_path = tmp_path / "github_output"
    output_path.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["GITHUB_REPOSITORY"] = _SIM_GITHUB_REPOSITORY
    env["RELEASE_VERSION"] = _SIM_RELEASE_VERSION
    env["GITHUB_SHA"] = _SIM_GITHUB_SHA
    env["SIM_GITHUB_SHA"] = _SIM_GITHUB_SHA
    env["GITHUB_OUTPUT"] = str(output_path)
    env["GH_STUB_TAG_MODE"] = tag_mode
    env["GH_STUB_RELEASE_MODE"] = release_mode

    result = subprocess.run(
        ["bash", str(script_path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    outputs: dict[str, str] = {}
    for line in output_path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            outputs[key] = value
    return result, outputs


def test_simulated_tag_confirmed_404_resumes_as_fresh_publish(tmp_path: Path) -> None:
    """End-to-end: a confirmed-404 tag lookup exits 0 with both resume flags
    false, never reaching the release-view lookup at all."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs = _run_tag_state_script(tmp_path, script, tag_mode="tag_confirmed_404")
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag_resume": "false", "release_resume": "false"}


def test_simulated_tag_lookup_rate_limited_fails_closed(tmp_path: Path) -> None:
    """End-to-end: a 403 rate-limit error from the tag lookup must fail the
    step closed (nonzero exit, no outputs written) rather than being read
    as tag-absent."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs = _run_tag_state_script(tmp_path, script, tag_mode="tag_rate_limited")
    assert result.returncode != 0
    assert "NOT confirmed" in result.stderr
    assert outputs == {}


def test_simulated_tag_lookup_network_error_fails_closed(tmp_path: Path) -> None:
    """End-to-end: a transport-level failure from the tag lookup must also
    fail closed, not be misread as tag-absent."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs = _run_tag_state_script(tmp_path, script, tag_mode="tag_network_error")
    assert result.returncode != 0
    assert "NOT confirmed" in result.stderr
    assert outputs == {}


def test_simulated_release_confirmed_absent_resumes_publication(tmp_path: Path) -> None:
    """End-to-end: tag exists at this commit, release lookup confirms
    absence ('release not found') -- resumes with tag_resume=true,
    release_resume=false, no error."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs = _run_tag_state_script(
        tmp_path, script, tag_mode="tag_exists", release_mode="release_confirmed_absent"
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag_resume": "true", "release_resume": "false"}


def test_simulated_release_lookup_rate_limited_fails_closed_after_tag_resume(tmp_path: Path) -> None:
    """End-to-end: tag exists at this commit (tag_resume=true is safely
    written), but the release lookup then hits a transient error -- must
    fail closed rather than guessing the Release is absent."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs = _run_tag_state_script(
        tmp_path, script, tag_mode="tag_exists", release_mode="release_rate_limited"
    )
    assert result.returncode != 0
    assert "NOT confirmed" in result.stderr
    assert outputs == {"tag_resume": "true"}


def test_simulated_release_already_exists_resumes_asset_attach(tmp_path: Path) -> None:
    """End-to-end: both the tag and its Release already exist at this
    commit -- the genuine safe-resume path, release_resume=true, no
    error."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs = _run_tag_state_script(
        tmp_path, script, tag_mode="tag_exists", release_mode="release_exists"
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag_resume": "true", "release_resume": "true"}


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
