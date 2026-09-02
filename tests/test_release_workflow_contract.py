"""Static contract for the canonical immutable release mechanism.

Pins the structure of `.github/workflows/release.yml` per
docs/planning/adrs/0129-canonical-immutable-release.md: a deliberate,
maintainer-dispatched trigger only; a fail-closed gate that verifies the
released commit is protected main's untampered current tip and that the
requested version matches `pyproject.toml`; a fresh full test-suite run; and
an immutable, never-reused git tag backing a real GitHub Release. The
workflow is two jobs (`verify`, read-only and credential-less; `publish`,
write-scoped) -- see `tests/test_release_workflow_idempotency_contract.py`
for the deeper resume/reject and least-privilege invariants that split
motivates.

Uses plain text assertions rather than a YAML parser, matching this
repository's existing workflow-contract convention (e.g.
`tests/test_nim_benchmark_workflow_contract.py`) and the Ponytail gate: no
new dependency (PyYAML is not otherwise used anywhere in this repository)
when substring/index assertions already prove the same structure. Where a
finding calls for more than "does this text appear anywhere," helpers below
bound the search to one job's own step block so the assertion proves real
step order and job scoping rather than incidental proximity.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/release.yml"
_CHECKS_GATE_SCRIPT_PATH = REPOSITORY_ROOT / "scripts/ci/release_checks_gate.sh"

_JOB_NAMES = ("verify", "publish")

# Fixed, deterministic values for the hand-simulation tests below --
# arbitrary, just stable and, critically, *distinct* so a real check-run
# from an earlier push-triggered workflow run is never accidentally
# mistaken for one of this release run's own (which the gate's real filter
# must exclude): _SIM_RUN_ID is the release workflow's own run id (the one
# GITHUB_RUN_ID is set to); _SIM_PRIOR_RUN_ID is the unrelated, earlier
# run id the stubbed push-triggered check-runs themselves carry.
_SIM_GITHUB_SHA = "cf69dc39457829c351277aad8096c24115d3991c"
_SIM_RUN_ID = "999999"
_SIM_PRIOR_RUN_ID = "888888"


def _workflow_text() -> str:
    """Return the release workflow's raw YAML text."""
    return _WORKFLOW_PATH.read_text(encoding="utf-8")


def _job_block(workflow: str, job_name: str) -> str:
    """Return one top-level job's own YAML text, steps and all.

    Bounded from the job's `  <job_name>:` line to the next known sibling
    job at the same two-space indent, or end of file for the last job.
    Keeping this to the two real job names (rather than a generic regex)
    avoids ever silently matching a step name that happens to look like a
    job key.
    """
    start = workflow.index(f"\n  {job_name}:\n")
    later_siblings = [
        workflow.index(f"\n  {sibling}:\n")
        for sibling in _JOB_NAMES
        if sibling != job_name and workflow.index(f"\n  {sibling}:\n") > start
    ]
    end = min(later_siblings) if later_siblings else len(workflow)
    return workflow[start:end]


def _step_names(block: str) -> list[str]:
    """Return a job block's `- name: ...` step names in file order."""
    return [
        line.split("- name:", 1)[1].strip()
        for line in block.splitlines()
        if line.strip().startswith("- name:")
    ]


def _expected_push_checks_json(workflow: str) -> str:
    """Return the raw `RELEASE_EXPECTED_PUSH_CHECKS` JSON literal's text."""
    marker = "RELEASE_EXPECTED_PUSH_CHECKS: '"
    start = workflow.index(marker) + len(marker)
    end = workflow.index("'", start)
    return workflow[start:end]


_STUB_GH_CHECK_RUNS = """#!/usr/bin/env bash
# Stub gh CLI: answers the checks-green gate's one gh call --
# `gh api repos/.../commits/$TARGET_SHA/check-runs?... --paginate --slurp`
# -- with the canned response file named by GH_STUB_CHECKS_JSON, so the
# gate's real jq filters run against deliberately-crafted scenarios instead
# of a live GitHub API. Requires the endpoint to actually name TARGET_SHA
# (not, say, a leftover GITHUB_SHA) so a regression back to gating on the
# wrong commit fails this stub rather than passing silently.
set -euo pipefail
if [ "$1" = "api" ]; then
    for arg in "$@"; do
        case "$arg" in
            *"commits/${TARGET_SHA}/check-runs"*) cat "${GH_STUB_CHECKS_JSON}"; exit 0 ;;
        esac
    done
fi
echo "unhandled stub gh invocation: $*" >&2
exit 98
"""


def _run_checks_gate_script(
    tmp_path: Path, checks_json: str, expected_json: str, run_id: str = _SIM_RUN_ID, target_sha: str = _SIM_GITHUB_SHA
) -> subprocess.CompletedProcess[str]:
    """Execute the real, unmodified `scripts/ci/release_checks_gate.sh` --
    the one script both `verify` and `publish` invoke -- against stubbed
    gh/data.

    Builds the same environment GitHub Actions would provide
    (`GITHUB_REPOSITORY`, `TARGET_SHA`, `GITHUB_RUN_ID`,
    `RELEASE_EXPECTED_PUSH_CHECKS`) plus a stub `gh` on `PATH`, then runs the
    shared script file directly -- never a hand-copied stand-in that could
    silently drift from what the workflow actually executes.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_stub = bin_dir / "gh"
    gh_stub.write_text(_STUB_GH_CHECK_RUNS, encoding="utf-8")
    gh_stub.chmod(0o755)

    checks_file = tmp_path / "checks.json"
    checks_file.write_text(checks_json, encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["GITHUB_REPOSITORY"] = "ContextualWisdomLab/contextual-orchestrator"
    env["TARGET_SHA"] = target_sha
    env["GITHUB_RUN_ID"] = run_id
    env["RELEASE_EXPECTED_PUSH_CHECKS"] = expected_json
    env["GH_STUB_CHECKS_JSON"] = str(checks_file)

    return subprocess.run(
        ["bash", str(_CHECKS_GATE_SCRIPT_PATH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _check_run(name: str, *, status: str = "completed", conclusion: str | None = "success", run_id: str = _SIM_PRIOR_RUN_ID, job: int = 1) -> dict:
    """Build one check-run entry for a stubbed `check-runs` response page."""
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "details_url": f"https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/{run_id}/jobs/{job}",
    }


def _check_runs_response(entries: list[dict]) -> str:
    """Render entries as one `--paginate --slurp` page, matching the real API shape."""
    return json.dumps([{"total_count": len(entries), "check_runs": entries}])


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


def test_gate_determines_tag_resume_state_via_the_commits_api() -> None:
    """A tag's existence is resolved through the commit-dereferencing API.

    Superseded by the idempotent resume/reject design (Devin finding 3): see
    `tests/test_release_workflow_idempotency_contract.py` for the full
    resume-vs-reject branching contract.
    """
    workflow = _workflow_text()
    verify_block = _job_block(workflow, "verify")
    assert 'repos/${GITHUB_REPOSITORY}/commits/v${RELEASE_VERSION}' in verify_block
    assert "tag_resume" in verify_block


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
    """A missing SBOM artifact, or a failed lookup, must warn, never abort.

    Bounded tightly to just the SBOM step's own body (the next step's
    heading is the boundary), and asserts the *mechanism* of non-fatality --
    each fallible `gh` call is guarded by an explicit `if !`, and the step
    does not opt into `set -e` (which would abort the whole step on the
    first failing command, including the permission-sensitive `gh run
    list`) -- rather than only checking that a warning string appears
    somewhere loosely nearby (Devin finding 4).
    """
    workflow = _workflow_text()
    verify_block = _job_block(workflow, "verify")
    sbom_step_index = verify_block.index("Fetch the CycloneDX SBOM")
    next_step_index = verify_block.index("Upload rendered notes and SBOM")
    sbom_block = verify_block[sbom_step_index:next_step_index]

    assert "set -euo pipefail" not in sbom_block, (
        "the SBOM step must not abort-on-error via -e; every fallible "
        "command needs its own explicit failure handling instead"
    )
    assert "if ! run_id=" in sbom_block
    assert "if ! gh run download" in sbom_block
    assert sbom_block.count("::warning::") >= 2


def test_concurrency_group_serializes_release_runs() -> None:
    """Two dispatched releases must never race the same tag push."""
    workflow = _workflow_text()
    concurrency_start = workflow.index("\nconcurrency:\n")
    jobs_start = workflow.index("\njobs:\n")
    concurrency_block = workflow[concurrency_start:jobs_start]
    assert "group: release" in concurrency_block
    assert "cancel-in-progress: false" in concurrency_block


def test_verify_job_has_read_only_permissions_and_no_persisted_credentials() -> None:
    """`verify` runs repository-controlled code (tests, note rendering) with
    no write token present and no persisted git credential (CodeRabbit
    CWE-269 hardening: least-privilege split, see the idempotency contract
    test file for the matching `publish`-side assertions)."""
    workflow = _workflow_text()
    verify_block = _job_block(workflow, "verify")
    assert "contents: read" in verify_block
    assert "actions: read" in verify_block
    assert "contents: write" not in verify_block
    assert "persist-credentials: false" in verify_block


def test_final_main_tip_check_happens_after_testing_and_note_rendering_but_before_tagging() -> None:
    """Devin finding 1: a second, authoritative main-tip check must run
    after every potentially long-running gate (the fresh test suite and
    note rendering) and before the tag is created -- not only at the start."""
    workflow = _workflow_text()
    test_run_index = workflow.index(
        "uv run --locked --extra api --extra db --extra queue --group dev python -m pytest -q"
    )
    notes_render_index = workflow.index("Render release notes from CHANGELOG.md")
    final_tip_check_index = workflow.index(
        "Re-verify protected main has not advanced since verification started"
    )
    tag_step_index = workflow.index("Create the annotated release tag")

    assert test_run_index < notes_render_index < final_tip_check_index < tag_step_index

    # The first (fast-fail) tip check still exists, distinct from this one.
    first_tip_check_index = workflow.index("current, untampered tip")
    assert first_tip_check_index < test_run_index < final_tip_check_index

    final_tip_check_block = workflow[final_tip_check_index:tag_step_index]
    assert 'repos/${GITHUB_REPOSITORY}/commits/main" --jq .sha' in final_tip_check_block
    assert 'if [ "${remote_head}" != "${GITHUB_SHA}" ]' in final_tip_check_block


def test_checks_read_permission_is_granted_in_both_jobs() -> None:
    """The checks-green gate (Devin follow-up finding: "Unchecked main
    checks permit releases") needs `checks: read` in both `verify` (fail
    fast, before the expensive test suite) and `publish` (the authoritative
    recheck right before anything is created)."""
    workflow = _workflow_text()
    verify_block = _job_block(workflow, "verify")
    publish_block = _job_block(workflow, "publish")
    assert "checks: read" in verify_block
    assert "checks: read" in publish_block


def test_gate_verifies_every_check_for_the_commit_is_complete_and_green() -> None:
    """`verify` must fail closed before running the expensive test suite if
    any check GitHub reports for TARGET_SHA (Security, Fuzz, ... -- whatever
    push-triggered workflows ran again on that commit) is still pending or
    did not conclude successfully. `verify`'s step just invokes the shared
    script (see `test_both_jobs_checks_green_step_calls_the_shared_script`
    and `test_checks_gate_script_content` below for the script's own real
    logic, kept in one place so `verify` and `publish` can never drift)."""
    workflow = _workflow_text()
    verify_block = _job_block(workflow, "verify")
    checks_step_index = verify_block.index("Verify every check reported for this commit is complete and green")
    test_suite_index = verify_block.index("Run the full required test suite fresh on this exact commit")
    assert checks_step_index < test_suite_index

    checks_block = verify_block[checks_step_index:test_suite_index]
    assert "scripts/ci/release_checks_gate.sh" in checks_block


def test_both_jobs_checks_green_step_calls_the_shared_script() -> None:
    """Neither job may inline its own copy of the checks-green jq filter --
    both must call the one shared script, so a fix in one can never
    silently fail to land in the other (CodeRabbit maintainability
    finding: the two copies previously drifted from each other unnoticed)."""
    workflow = _workflow_text()
    verify_block = _job_block(workflow, "verify")
    publish_block = _job_block(workflow, "publish")
    assert _CHECKS_GATE_SCRIPT_PATH.exists()
    for job_name, block, heading in (
        ("verify", verify_block, "Verify every check reported for this commit is complete and green"),
        ("publish", publish_block, "Re-verify every check reported for this commit is complete and green"),
    ):
        step_index = block.index(heading)
        step_end = block.index("\n\n", step_index)
        step_text = block[step_index:step_end]
        assert "run: bash scripts/ci/release_checks_gate.sh" in step_text, (
            f"{job_name}'s checks-green step must call the shared script, not inline its own jq filter"
        )
        # No job-local reimplementation of the filter itself.
        assert '.status != "completed"' not in step_text
        assert "check_runs[]?" not in step_text


def test_checks_gate_script_content() -> None:
    """The shared script itself carries the real jq filters and fail-closed
    structure -- pinned here once instead of duplicated per job."""
    script = _CHECKS_GATE_SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'repos/${GITHUB_REPOSITORY}/commits/${TARGET_SHA}/check-runs' in script
    assert '.status != "completed"' in script
    assert '["success","skipped","neutral"]' in script
    assert 'if [ "${not_ready_count}" != "0" ]' in script
    assert "exit 1" in script
    # Excludes this release run's own check-runs -- otherwise a
    # workflow_dispatch run would always find itself unfinished and deadlock.
    assert "GITHUB_RUN_ID" in script


def test_expected_push_checks_matches_this_repositorys_actual_push_triggered_jobs() -> None:
    """`RELEASE_EXPECTED_PUSH_CHECKS` (Devin finding: "Missing checks pass
    release gate") must track the real job `name:` values `ci.yml`,
    `fuzz.yml`, and `security.yml` declare for their push-triggered jobs --
    not a hand-copied list that can silently drift once one of those jobs
    is renamed, added, or removed."""
    workflow = _workflow_text()
    expected = json.loads(_expected_push_checks_json(workflow))
    assert len(expected) == len(set(expected)), "expected-checks list has a duplicate"

    def _job_names(path: Path) -> list[str]:
        return re.findall(r"^ {4}name: (.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)

    push_triggered_job_names = (
        _job_names(REPOSITORY_ROOT / ".github/workflows/ci.yml")
        + _job_names(REPOSITORY_ROOT / ".github/workflows/fuzz.yml")
        + _job_names(REPOSITORY_ROOT / ".github/workflows/security.yml")
    )
    assert set(expected) == set(push_triggered_job_names)
    assert len(expected) == len(push_triggered_job_names), "a push-triggered job name is duplicated"


def test_checks_gate_requires_expected_checks_before_checking_they_are_green() -> None:
    """The shared script must reference the expected-checks env var and
    compute `missing_checks`/`missing_count` *before* the pre-existing
    `not_ready`/`not_ready_count` gate -- registration must be confirmed
    before conclusions are even inspected. One script, one order, used by
    both jobs -- see `test_both_jobs_checks_green_step_calls_the_shared_script`."""
    script = _CHECKS_GATE_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "RELEASE_EXPECTED_PUSH_CHECKS" in script
    missing_index = script.index("missing_checks=")
    missing_count_index = script.index('if [ "${missing_count}" != "0" ]')
    not_ready_index = script.index("not_ready=")
    not_ready_count_index = script.index('if [ "${not_ready_count}" != "0" ]')
    assert missing_index < missing_count_index < not_ready_index < not_ready_count_index


def test_checks_gate_zero_registered_checks_fails_closed(tmp_path: Path) -> None:
    """Devin finding: dispatching moments after a merge, before GitHub has
    registered ANY of this new tip's push-triggered check-runs, must not
    vacuously pass -- an empty `check-runs` report is "not ready", not
    "nothing to block on". Executes the real, unmodified shared script."""
    workflow = _workflow_text()
    expected_json = _expected_push_checks_json(workflow)
    expected_count = len(json.loads(expected_json))

    result = _run_checks_gate_script(tmp_path, _check_runs_response([]), expected_json)

    assert result.returncode != 0, result.stderr
    assert f"{expected_count} expected push-triggered check(s)" in result.stderr
    assert "have not registered yet" in result.stderr


def test_checks_gate_some_but_not_all_expected_checks_green_fails_closed(tmp_path: Path) -> None:
    """Some, but not all, of the expected push-triggered checks have
    registered, and every one that has is green -- must still fail: the
    still-missing ones could be pending, failing, or not yet dispatched at
    all, and a partial report must never be read as sufficient."""
    workflow = _workflow_text()
    expected_json = _expected_push_checks_json(workflow)
    expected_names = json.loads(expected_json)
    present = {"Full unit and contract suite", "CodeQL analysis"}
    missing_names = [name for name in expected_names if name not in present]

    partial = _check_runs_response(
        [_check_run("Full unit and contract suite", job=1), _check_run("CodeQL analysis", job=2)]
    )
    result = _run_checks_gate_script(tmp_path, partial, expected_json)

    assert result.returncode != 0, result.stderr
    assert f"{len(missing_names)} expected push-triggered check(s)" in result.stderr
    for name in missing_names:
        assert name in result.stderr


def test_checks_gate_all_expected_checks_registered_and_green_passes(tmp_path: Path) -> None:
    """All expected push-triggered checks are registered and green (plus
    this release run's own still-in-flight check-runs, correctly excluded
    via GITHUB_RUN_ID) -- the gate must pass."""
    workflow = _workflow_text()
    expected_json = _expected_push_checks_json(workflow)
    expected_names = json.loads(expected_json)

    entries = [_check_run(name, job=i) for i, name in enumerate(expected_names, start=1)]
    # This release run's own check-runs (verify's and publish's), which
    # share GITHUB_RUN_ID and must be excluded rather than deadlocking the
    # gate on itself.
    entries.append(_check_run("Verify release preconditions (read-only)", status="in_progress", conclusion=None, run_id=_SIM_RUN_ID, job=7))
    entries.append(_check_run("Publish canonical immutable release", status="queued", conclusion=None, run_id=_SIM_RUN_ID, job=8))

    result = _run_checks_gate_script(tmp_path, _check_runs_response(entries), expected_json)

    assert result.returncode == 0, result.stderr


def test_checks_gate_all_expected_registered_but_one_still_pending_fails_closed(tmp_path: Path) -> None:
    """All expected checks have registered (so the missing-checks gate
    passes), but one is still in flight -- the pre-existing not-ready/green
    gate must still catch it."""
    workflow = _workflow_text()
    expected_json = _expected_push_checks_json(workflow)
    expected_names = json.loads(expected_json)

    entries = [_check_run(name, job=i) for i, name in enumerate(expected_names, start=1)]
    entries[-1] = _check_run(expected_names[-1], status="in_progress", conclusion=None, job=len(expected_names))

    result = _run_checks_gate_script(tmp_path, _check_runs_response(entries), expected_json)

    assert result.returncode != 0, result.stderr
    assert "have not registered yet" not in result.stderr
    assert "not both complete and green" in result.stderr


def test_checks_gate_evaluates_target_sha_not_the_dispatch_commit(tmp_path: Path) -> None:
    """A resume must gate on TARGET_SHA (the tag's own target commit), not
    whatever GITHUB_SHA/current-main happens to be -- the shared script
    only ever reads TARGET_SHA, so passing a distinct value here proves it
    is genuinely the commit being checked, not an incidental match."""
    workflow = _workflow_text()
    expected_json = _expected_push_checks_json(workflow)
    expected_names = json.loads(expected_json)
    older_target_sha = "a" * 40

    entries = [_check_run(name, job=i) for i, name in enumerate(expected_names, start=1)]
    result = _run_checks_gate_script(tmp_path, _check_runs_response(entries), expected_json, target_sha=older_target_sha)

    assert result.returncode == 0, result.stderr


def test_final_checks_green_recheck_happens_right_after_the_final_tip_check() -> None:
    """`publish` must re-verify checks are still green immediately after its
    final main-tip recheck -- both authoritative gates cluster together,
    right after checkout, before anything else runs."""
    workflow = _workflow_text()
    publish_block = _job_block(workflow, "publish")
    final_tip_check_index = publish_block.index(
        "Re-verify protected main has not advanced since verification started"
    )
    final_checks_index = publish_block.index("Re-verify every check reported for this commit is complete and green")
    download_index = publish_block.index("Download the release notes and SBOM")
    tag_step_index = publish_block.index("Create the annotated release tag")
    assert final_tip_check_index < final_checks_index < download_index < tag_step_index

    checks_block = publish_block[final_checks_index:download_index]
    assert "scripts/ci/release_checks_gate.sh" in checks_block


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
