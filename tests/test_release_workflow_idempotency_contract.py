"""Idempotent-retry and least-privilege contract for the release workflow.

Covers the design that resolves five related Devin/CodeRabbit findings on
`.github/workflows/release.yml`, kept in one file because they share a root
cause -- the tag (and, now, the Release object itself) is created before the
fallible SBOM-asset step, so any failure after that must be safely
retryable without ever moving the tag or double-publishing:

- The exact refs/tags resume-vs-reject branching: an already-existing tag that points
  at this exact commit is a safe resume; a tag pointing at any other commit
  is rejected rather than silently accepted or overwritten.
- The Release resume-vs-create branching (`release_resume`, a Devin
  follow-up finding distinct from the tag one above): a GitHub Release that
  already exists for this exact commit is *also* a safe resume -- `gh
  release create` can publish the Release object and then fail partway
  through uploading its assets, so "the Release already exists" must not be
  treated as "nothing left to do." `publish` always attempts the
  mandatory SBOM asset attach afterward, whether the Release was just
  created or already existed.
- Confirmed-absence vs transient-failure classification for both lookups
  (Devin's later finding, "API failures block release recovery"): a failed
  tag lookup or `gh release view` call is *not* automatically "absent" --
  only a confirmed HTTP 404 (tag) or "release not found" (Release) means
  that; any other failure (rate limit, auth, network blip, a GitHub 5xx)
  fails the step closed instead of risking a wrong fresh-create attempt
  against unconfirmed state. See the real bash+stub-`gh` simulation near
  the end of this file for end-to-end coverage beyond text assertions.
- `actions: read` is granted at the `verify` job's scope for the mandatory
  exact-commit SBOM lookup and nowhere else.
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
        "Determine whether this is a fresh publish or a resume, and the exact commit to operate on"
    )
    next_step_start = verify_block.index(
        "Check out the exact commit this run will operate on"
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
    assert 'echo "tag_resume=false"' in verify_block
    assert 'echo "tag_resume=true"' in verify_block
    assert 'echo "release_resume=false"' in verify_block
    assert 'echo "release_resume=true" >> "${GITHUB_OUTPUT}"' in verify_block
    assert "outputs:" in verify_block
    assert "tag_resume: ${{ steps.tag_state.outputs.tag_resume }}" in verify_block
    assert "release_resume: ${{ steps.tag_state.outputs.release_resume }}" in verify_block
    assert "target_sha: ${{ steps.tag_state.outputs.target_sha }}" in verify_block


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
    lookup_index = step.index('if ! tag_ref_output=')
    confirmed_404_index = step.index('grep -q "HTTP 404"', lookup_index)
    inner_fi_index = step.index('\n            fi\n', confirmed_404_index)
    confirmed_404_branch = step[confirmed_404_index:inner_fi_index]
    assert "::error::" not in confirmed_404_branch
    assert 'echo "tag_resume=false"' in confirmed_404_branch
    assert 'echo "release_resume=false"' in confirmed_404_branch
    assert "exit 0" in confirmed_404_branch


def test_tag_lookup_non_404_error_fails_closed_not_treated_as_absent() -> None:
    """Devin finding ("API failures block release recovery"): a transient
    rate-limit, auth, network, or 5xx failure from the tag lookup must
    never be silently treated as 'tag absent' -- it must fail this step
    closed (distinct exit 1, after the confirmed-404 short-circuit already
    had its chance to `exit 0` first) so a later retry can resolve cleanly
    instead of compounding a wrong assumption."""
    step = _tag_state_step(_workflow_text())
    lookup_index = step.index('if ! tag_ref_output=')
    confirmed_404_fi_index = step.index('\n            fi\n', lookup_index)
    outer_fi_index = step.index('\n          fi\n', confirmed_404_fi_index)
    fail_closed_branch = step[confirmed_404_fi_index:outer_fi_index]
    assert "::error::" in fail_closed_branch
    assert "exit 1" in fail_closed_branch
    assert "NOT confirmed" in fail_closed_branch
    assert "tag_resume=" not in fail_closed_branch
    assert "release_resume=" not in fail_closed_branch


def test_tag_pointing_elsewhere_is_checked_against_main_via_ancestry_not_rejected_outright() -> None:
    """A tag pointing at a commit other than this dispatch's own GITHUB_SHA
    is *not* automatically rejected (Devin finding: "Tag-only retries
    mislabel releases") -- main may simply have advanced past the tag's
    target since it was pushed. The mismatch branch must consult the
    compare API to decide ancestor-of-main (safe resume) vs genuinely
    elsewhere (reject), not exit 1 unconditionally."""
    step = _tag_state_step(_workflow_text())
    assert '${tag_commit}" != "${GITHUB_SHA}' in step
    mismatch_index = step.index('${tag_commit}" != "${GITHUB_SHA}')
    compare_index = step.index("repos/${GITHUB_REPOSITORY}/compare/${tag_commit}...main", mismatch_index)
    case_index = step.index('case "${compare_status}" in', compare_index)
    assert mismatch_index < compare_index < case_index


def test_tag_pointing_at_a_commit_not_an_ancestor_of_main_is_rejected_not_moved() -> None:
    """A tag whose target commit is genuinely not part of main's history
    (compare status anything other than identical/ahead) must still fail
    the run outright -- a release tag is never moved onto, or reused for,
    a different commit."""
    step = _tag_state_step(_workflow_text())
    case_index = step.index('case "${compare_status}" in')
    default_arm_index = step.index("*)", case_index)
    esac_index = step.index("esac", default_arm_index)
    default_arm = step[default_arm_index:esac_index]
    assert "::error::" in default_arm
    assert "exit 1" in default_arm
    assert "never moved onto a different commit" in default_arm

    identical_ahead_index = step.index("identical|ahead)", case_index)
    assert case_index < identical_ahead_index < default_arm_index, (
        "the ancestor (resume) arm must be checked before the catch-all reject arm"
    )
    resume_arm = step[identical_ahead_index:default_arm_index]
    assert "::error::" not in resume_arm
    assert "exit 1" not in resume_arm


def test_tag_matching_commit_sets_tag_resume_before_branching_on_release_existence() -> None:
    """Once the tag is confirmed safe to resume from (either it points at
    this exact commit, or it is an ancestor of main's current tip),
    `tag_resume` is set unconditionally -- only whether the GitHub Release
    itself already exists (`release_resume`) still needs its own branch."""
    step = _tag_state_step(_workflow_text())
    mismatch_index = step.index('${tag_commit}" != "${GITHUB_SHA}')
    target_sha_assignment_index = step.index('target_sha="${tag_commit}"')
    tag_resume_true_index = step.index('echo "tag_resume=true"')
    release_view_index = step.index('gh release view "v${RELEASE_VERSION}"')
    assert mismatch_index < target_sha_assignment_index < tag_resume_true_index < release_view_index


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


def test_required_release_asset_attach_always_runs_and_fails_closed() -> None:
    """Whether the Release was just created fresh or already existed on a
    resumed run, attaching the SBOM asset must still be attempted. A failed
    attach fails this run closed and a later dispatch resumes without moving
    the tag."""
    workflow = _workflow_text()
    publish_block = _job_block(workflow, "publish")
    create_step_index = publish_block.index("Create the GitHub Release")
    attach_step_index = publish_block.index("Attach required release SBOM")
    assert create_step_index < attach_step_index

    attach_step = publish_block[attach_step_index:]
    step_header = attach_step[: attach_step.index("run:")]
    # The attach step itself carries no `if:` gate -- it must run whether
    # `Create the GitHub Release` ran or was skipped as already-resumed.
    assert "if:" not in step_header
    assert "set -euo pipefail" in attach_step
    assert "if ! gh release upload" in attach_step
    assert "::error::" in attach_step
    assert "exit 1" in attach_step
    assert "--clobber" in attach_step


# --- Confirmed-absence vs transient-failure, and ancestor-vs-conflict,
# --- real-execution simulation (Devin findings: "API failures block
# --- release recovery" and "Tag-only retries mislabel releases") -----------
#
# The tests above prove the *branch structure* of the tag_state step's real
# YAML text. These go further: they execute that exact, unmodified script
# (never a hand-copied stand-in that could silently drift from it) under
# bash, against a stub `gh` that distinguishes calls by the actual endpoint
# requested, covering every branch end-to-end -- exit code, the actual
# GITHUB_OUTPUT lines written, and the actual GITHUB_ENV (TARGET_SHA) line
# written -- the same real-execution technique
# tests/test_release_workflow_contract.py uses for the checks-green gate.


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


# A resume-from-an-older-commit case (main has advanced past the tag) and a
# genuinely-elsewhere case (not an ancestor of main at all) need SHAs
# distinct from both each other and from _SIM_GITHUB_SHA, so a test can
# never pass by accident if the script mixed the two commits up.
_SIM_OLDER_TAG_SHA = "a" * 40
_SIM_UNRELATED_TAG_SHA = "b" * 40


_STUB_GH_TAG_RELEASE_LOOKUP = """#!/usr/bin/env bash
# Stub gh CLI for hand-simulating the tag_state step's three lookups (tag
# existence, main-ancestry compare, Release existence) against
# deliberately-crafted success/confirmed-absence/transient-failure cases,
# selected via GH_STUB_TAG_MODE, GH_STUB_COMPARE_MODE, and
# GH_STUB_RELEASE_MODE. Distinguishes gh invocations by the actual endpoint
# requested ($2), not only by which mode env var happens to be set -- so a
# new gh call this step adds later would fail this stub with an explicit
# "unhandled" error rather than silently being answered by the wrong
# canned response (CodeRabbit test-hardening finding).
tag_mode="${GH_STUB_TAG_MODE:-}"
compare_mode="${GH_STUB_COMPARE_MODE:-}"
release_mode="${GH_STUB_RELEASE_MODE:-}"
tag_sha="${GH_STUB_TAG_SHA:-${SIM_GITHUB_SHA}}"

if [ "$1" = "api" ]; then
  request="$2"
  case "${request}" in
    *"/git/ref/tags/v${RELEASE_VERSION}"*)
      case "${tag_mode}" in
        tag_confirmed_404)
          echo "gh: Not Found (HTTP 404)" >&2
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
          printf 'commit\t%s\n' "${tag_sha}"
          exit 0
          ;;
        *) echo "unhandled stub gh api tag mode: ${tag_mode}" >&2; exit 97 ;;
      esac
      ;;
    *"/compare/"*)
      case "${compare_mode}" in
        identical) echo "identical"; exit 0 ;;
        ahead) echo "ahead"; exit 0 ;;
        behind) echo "behind"; exit 0 ;;
        diverged) echo "diverged"; exit 0 ;;
        compare_error)
          echo "gh: API rate limit exceeded for user ID 123. (HTTP 403)" >&2
          exit 1
          ;;
        *) echo "unhandled stub gh api compare mode: ${compare_mode}" >&2; exit 97 ;;
      esac
      ;;
    *)
      echo "unhandled stub gh api request: $*" >&2
      exit 98
      ;;
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
    tmp_path: Path,
    script: str,
    *,
    tag_mode: str,
    release_mode: str = "",
    compare_mode: str = "",
    tag_sha: str = _SIM_GITHUB_SHA,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], dict[str, str]]:
    """Execute the real tag_state script against the stub gh above.

    Returns the completed process, the `GITHUB_OUTPUT` lines actually
    written parsed into a dict (empty if the step exited before writing
    any, e.g. the fail-closed branches), and the `GITHUB_ENV` lines
    actually written parsed the same way (TARGET_SHA, once the run reaches
    far enough to set it).
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
    env_path = tmp_path / "github_env"
    env_path.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["GITHUB_REPOSITORY"] = _SIM_GITHUB_REPOSITORY
    env["RELEASE_VERSION"] = _SIM_RELEASE_VERSION
    env["GITHUB_SHA"] = _SIM_GITHUB_SHA
    env["SIM_GITHUB_SHA"] = _SIM_GITHUB_SHA
    env["GITHUB_OUTPUT"] = str(output_path)
    env["GITHUB_ENV"] = str(env_path)
    env["GH_STUB_TAG_MODE"] = tag_mode
    env["GH_STUB_RELEASE_MODE"] = release_mode
    env["GH_STUB_COMPARE_MODE"] = compare_mode
    env["GH_STUB_TAG_SHA"] = tag_sha

    result = subprocess.run(
        ["bash", str(script_path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    def _parse(path: Path) -> dict[str, str]:
        parsed: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                parsed[key] = value
        return parsed

    return result, _parse(output_path), _parse(env_path)


def test_simulated_tag_confirmed_404_resumes_as_fresh_publish(tmp_path: Path) -> None:
    """End-to-end: a confirmed-404 tag lookup exits 0 with both resume flags
    false and target_sha set to the dispatch commit, never reaching the
    ancestry-compare or release-view lookups at all."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs, env_vars = _run_tag_state_script(tmp_path, script, tag_mode="tag_confirmed_404")
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag_resume": "false", "release_resume": "false", "target_sha": _SIM_GITHUB_SHA}
    assert env_vars == {"TARGET_SHA": _SIM_GITHUB_SHA}


def test_simulated_tag_lookup_rate_limited_fails_closed(tmp_path: Path) -> None:
    """End-to-end: a 403 rate-limit error from the tag lookup must fail the
    step closed (nonzero exit, no outputs written) rather than being read
    as tag-absent."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs, env_vars = _run_tag_state_script(tmp_path, script, tag_mode="tag_rate_limited")
    assert result.returncode != 0
    assert "NOT confirmed" in result.stderr
    assert outputs == {}
    assert env_vars == {}


def test_simulated_tag_lookup_network_error_fails_closed(tmp_path: Path) -> None:
    """End-to-end: a transport-level failure from the tag lookup must also
    fail closed, not be misread as tag-absent."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs, env_vars = _run_tag_state_script(tmp_path, script, tag_mode="tag_network_error")
    assert result.returncode != 0
    assert "NOT confirmed" in result.stderr
    assert outputs == {}
    assert env_vars == {}


def test_simulated_tag_at_the_dispatch_commit_resumes_without_a_compare_call(tmp_path: Path) -> None:
    """End-to-end: the tag exists and already points at this exact dispatch
    commit (main has not advanced at all) -- the original, still-supported
    resume case. No ancestry compare is needed (and the stub would fail
    the run if one were attempted with no compare mode configured), and
    target_sha equals the dispatch commit."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs, env_vars = _run_tag_state_script(
        tmp_path, script, tag_mode="tag_exists", tag_sha=_SIM_GITHUB_SHA, release_mode="release_confirmed_absent"
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag_resume": "true", "release_resume": "false", "target_sha": _SIM_GITHUB_SHA}
    assert env_vars == {"TARGET_SHA": _SIM_GITHUB_SHA}


def test_simulated_tag_resumes_from_an_older_ancestor_commit_after_main_advanced(tmp_path: Path) -> None:
    """The real bug fix, end-to-end: the tag exists and points at an OLDER
    commit than this dispatch's GITHUB_SHA (main has advanced since the tag
    was pushed -- a tag-only interrupted publication). The ancestry compare
    reports "ahead" (the tag's commit is an ancestor of main's current
    tip), so this resumes safely using the TAG'S OWN commit as target_sha,
    never the newer dispatch commit -- exactly the scenario that was
    previously rejected outright as a false conflict."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs, env_vars = _run_tag_state_script(
        tmp_path,
        script,
        tag_mode="tag_exists",
        tag_sha=_SIM_OLDER_TAG_SHA,
        compare_mode="ahead",
        release_mode="release_confirmed_absent",
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag_resume": "true", "release_resume": "false", "target_sha": _SIM_OLDER_TAG_SHA}
    assert env_vars == {"TARGET_SHA": _SIM_OLDER_TAG_SHA}


def test_simulated_tag_resumes_when_compare_reports_identical(tmp_path: Path) -> None:
    """Defensive coverage of the compare API's "identical" status alongside
    "ahead" -- both mean the tag's target commit is (or was) main's own
    tip, so both are safe to resume from."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs, env_vars = _run_tag_state_script(
        tmp_path,
        script,
        tag_mode="tag_exists",
        tag_sha=_SIM_OLDER_TAG_SHA,
        compare_mode="identical",
        release_mode="release_confirmed_absent",
    )
    assert result.returncode == 0, result.stderr
    assert outputs["tag_resume"] == "true"
    assert outputs["target_sha"] == _SIM_OLDER_TAG_SHA
    assert env_vars == {"TARGET_SHA": _SIM_OLDER_TAG_SHA}


@pytest.mark.parametrize("compare_status", ["diverged", "behind"])
def test_simulated_tag_pointing_at_a_non_ancestor_commit_is_rejected(tmp_path: Path, compare_status: str) -> None:
    """The tag exists but points at a commit that is genuinely not part of
    main's history (never main's tip at any point, or main's tip is itself
    behind it) -- a real conflict, still rejected outright. No outputs are
    written; the tag is never moved or reused."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs, env_vars = _run_tag_state_script(
        tmp_path,
        script,
        tag_mode="tag_exists",
        tag_sha=_SIM_UNRELATED_TAG_SHA,
        compare_mode=compare_status,
    )
    assert result.returncode != 0
    assert "never moved onto a different commit" in result.stderr
    assert _SIM_UNRELATED_TAG_SHA in result.stderr
    assert outputs == {}
    assert env_vars == {}


def test_simulated_compare_lookup_error_fails_closed(tmp_path: Path) -> None:
    """A transient failure of the ancestry-compare call itself (rate limit,
    network, 5xx) must fail this step closed via the script's `set -e`,
    the same fail-closed default every other lookup in this step handles
    explicitly -- never silently treated as either a safe resume or a
    confirmed conflict."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs, env_vars = _run_tag_state_script(
        tmp_path,
        script,
        tag_mode="tag_exists",
        tag_sha=_SIM_OLDER_TAG_SHA,
        compare_mode="compare_error",
    )
    assert result.returncode != 0
    assert outputs == {}
    assert env_vars == {}


def test_simulated_release_confirmed_absent_resumes_publication(tmp_path: Path) -> None:
    """End-to-end: tag exists at this commit, release lookup confirms
    absence ('release not found') -- resumes with tag_resume=true,
    release_resume=false, no error."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs, env_vars = _run_tag_state_script(
        tmp_path, script, tag_mode="tag_exists", release_mode="release_confirmed_absent"
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag_resume": "true", "release_resume": "false", "target_sha": _SIM_GITHUB_SHA}
    assert env_vars == {"TARGET_SHA": _SIM_GITHUB_SHA}


def test_simulated_release_lookup_rate_limited_fails_closed_after_tag_resume(tmp_path: Path) -> None:
    """End-to-end: tag exists at this commit (tag_resume=true and
    target_sha are safely written), but the release lookup then hits a
    transient error -- must fail closed rather than guessing the Release
    is absent."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs, env_vars = _run_tag_state_script(
        tmp_path, script, tag_mode="tag_exists", release_mode="release_rate_limited"
    )
    assert result.returncode != 0
    assert "NOT confirmed" in result.stderr
    assert outputs == {"tag_resume": "true", "target_sha": _SIM_GITHUB_SHA}
    assert env_vars == {"TARGET_SHA": _SIM_GITHUB_SHA}


def test_simulated_release_already_exists_resumes_asset_attach(tmp_path: Path) -> None:
    """End-to-end: both the tag and its Release already exist at this
    commit -- the genuine safe-resume path, release_resume=true, no
    error."""
    workflow = _workflow_text()
    script = _tag_state_script(workflow)
    result, outputs, env_vars = _run_tag_state_script(
        tmp_path, script, tag_mode="tag_exists", release_mode="release_exists"
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag_resume": "true", "release_resume": "true", "target_sha": _SIM_GITHUB_SHA}
    assert env_vars == {"TARGET_SHA": _SIM_GITHUB_SHA}


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
    assert step_names[1] == "Re-verify protected main has not advanced since verification started (fresh publish only)"


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
