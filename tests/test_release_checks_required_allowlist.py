"""The release checks gate certifies a commit from ONE security.yml push run.

`scripts/ci/release_checks_gate.sh` first required every check-run on the
release commit to be green, then (first revision of this change) every
check-run carrying a required name. Both are wrong on protected main:

- security.yml's weekly `schedule` runs execute on main's tip and their jobs
  are `if: github.event_name != 'schedule'`, so they leave skipped (or failed)
  check-runs under the same required names on the same commit -- one old
  scheduled run blocked a SHA forever;
- hourly maintenance workflows (opencode-hourly-loop.yml,
  provider-catalog-sync.yml) attach failing or in-flight check-runs too.

The gate now selects the newest push-triggered `.github/workflows/security.yml`
run on main for exactly TARGET_SHA (highest run id, then run_attempt) and
evaluates only that run's jobs (explicit `filter=latest`) against the
`RELEASE_EXPECTED_PUSH_CHECKS` allowlist, failing closed when the run is
missing or unfinished or a required job is missing or not `success`.

Executes the real, unmodified script against a stubbed `gh` that serves the
Actions runs/jobs API.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPOSITORY_ROOT / ".github/workflows"
WORKFLOW_PATH = WORKFLOWS / "release.yml"
GATE_PATH = REPOSITORY_ROOT / "scripts/ci/release_checks_gate.sh"
TARGET_SHA = "cf69dc39457829c351277aad8096c24115d3991c"
SECURITY = ".github/workflows/security.yml"

REQUIRED = (
    "Tests and package quality",
    "Property and coverage-guided fuzzing",
    "Rust workspace gate",
    "CodeQL, supply chain, and SBOM",
)

_STUB_GH = r"""#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${GH_STUB_DIR}/calls.log"
if [ "$1" = "api" ]; then
    case " $* " in *" --paginate --slurp "*) ;; *) echo "missing --paginate --slurp: $*" >&2; exit 97 ;; esac
    prefix="repos/${GITHUB_REPOSITORY}/actions/runs"
    case "$2" in
        "${prefix}?head_sha=${TARGET_SHA}&event=push&per_page=100")
            cat "${GH_STUB_DIR}/runs.json"; exit 0 ;;
        "${prefix}/"*"/jobs?filter=latest&per_page=100")
            run_id="${2#"${prefix}/"}"; run_id="${run_id%%/*}"
            if [ -f "${GH_STUB_DIR}/jobs-${run_id}.json" ]; then cat "${GH_STUB_DIR}/jobs-${run_id}.json"; exit 0; fi ;;
    esac
fi
echo "unhandled stub gh invocation: $*" >&2
exit 98
"""


def _expected_checks_json() -> str:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    marker = "RELEASE_EXPECTED_PUSH_CHECKS: '"
    start = workflow.index(marker) + len(marker)
    return workflow[start : workflow.index("'", start)]


def _run(
    run_id: int,
    *,
    attempt: int = 1,
    event: str = "push",
    path: str = SECURITY,
    branch: str = "main",
    sha: str = TARGET_SHA,
    status: str = "completed",
) -> dict[str, object]:
    return {
        "id": run_id,
        "run_attempt": attempt,
        "event": event,
        "path": path,
        "head_branch": branch,
        "head_sha": sha,
        "status": status,
        "html_url": f"https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/{run_id}",
    }


def _jobs(conclusion: str | None = "success", *, status: str = "completed", names=REQUIRED) -> list[dict[str, object]]:
    return [
        {"id": index, "name": name, "status": status, "conclusion": conclusion}
        for index, name in enumerate(names, start=1)
    ]


def _green() -> list[dict[str, object]]:
    return _jobs()


def _gate(
    tmp_path: Path,
    runs: list[dict[str, object]],
    jobs: dict[int, list[dict[str, object]]],
    expected_json: str | None = None,
) -> subprocess.CompletedProcess[str]:
    stub_dir = tmp_path / "gh-stub"
    stub_dir.mkdir()
    (stub_dir / "runs.json").write_text(
        json.dumps([{"total_count": len(runs), "workflow_runs": runs}]), encoding="utf-8"
    )
    for run_id, run_jobs in jobs.items():
        (stub_dir / f"jobs-{run_id}.json").write_text(
            json.dumps([{"total_count": len(run_jobs), "jobs": run_jobs}]), encoding="utf-8"
        )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(_STUB_GH, encoding="utf-8")
    gh.chmod(0o755)
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "GITHUB_REPOSITORY": "ContextualWisdomLab/contextual-orchestrator",
            "TARGET_SHA": TARGET_SHA,
            "RELEASE_EXPECTED_PUSH_CHECKS": _expected_checks_json() if expected_json is None else expected_json,
            "GH_STUB_DIR": str(stub_dir),
        }
    )
    env.pop("GITHUB_RUN_ID", None)
    return subprocess.run(
        ["bash", str(GATE_PATH)], env=env, capture_output=True, text=True, check=False, timeout=30
    )


def _jobs_read_for(tmp_path: Path) -> list[str]:
    calls = (tmp_path / "gh-stub/calls.log").read_text(encoding="utf-8").splitlines()
    return [re.search(r"actions/runs/(\d+)/jobs", call).group(1) for call in calls if "/jobs?" in call]


# --- Scenarios from the Completer-Finisher review ---------------------------


def test_schedule_run_with_skipped_and_failed_jobs_does_not_block_a_green_push_run(tmp_path: Path) -> None:
    schedule_skipped = _run(900, event="schedule")
    schedule_failed = _run(950, event="schedule")
    push = _run(800)
    result = _gate(
        tmp_path,
        [schedule_skipped, schedule_failed, push],
        {900: _jobs("skipped"), 950: _jobs("failure"), 800: _green()},
    )
    assert result.returncode == 0, result.stderr
    assert _jobs_read_for(tmp_path) == ["800"]


def test_red_push_run_fails(tmp_path: Path) -> None:
    jobs = _green()
    jobs[1] = {**jobs[1], "conclusion": "failure"}
    result = _gate(tmp_path, [_run(800), _run(900, event="schedule")], {800: jobs, 900: _green()})
    assert result.returncode != 0
    assert "are not complete with conclusion success" in result.stderr
    assert REQUIRED[1] in result.stderr


def test_rerun_with_higher_run_attempt_wins(tmp_path: Path) -> None:
    # The list API reports the latest attempt; a stale attempt-1 entry for the
    # same run must never be chosen over attempt 2.
    runs = [_run(800, attempt=1), _run(800, attempt=2)]
    result = _gate(tmp_path, runs, {800: _green()})
    assert result.returncode == 0, result.stderr
    assert "attempt 2" in result.stdout


def test_newest_attempt_red_fails_even_if_an_older_attempt_was_green(tmp_path: Path) -> None:
    runs = [_run(800, attempt=2), _run(800, attempt=1)]
    result = _gate(tmp_path, runs, {800: _jobs("failure")})
    assert result.returncode != 0
    assert "attempt 2" in result.stdout


def test_newer_push_run_supersedes_an_older_red_one(tmp_path: Path) -> None:
    result = _gate(tmp_path, [_run(700), _run(800)], {700: _jobs("failure"), 800: _green()})
    assert result.returncode == 0, result.stderr
    assert _jobs_read_for(tmp_path) == ["800"]


@pytest.mark.parametrize(
    "runs",
    [
        [],
        [_run(900, event="schedule")],
        [_run(901, event="workflow_dispatch")],
        [_run(902, path=".github/workflows/release.yml")],
        [_run(903, path=".github/workflows/opencode-hourly-loop.yml")],
        [_run(904, branch="feature/x")],
        [_run(905, sha="a" * 40)],
    ],
    ids=["none", "schedule-only", "dispatch-only", "other-workflow", "hourly-loop", "other-branch", "other-sha"],
)
def test_missing_security_push_run_fails_closed(tmp_path: Path, runs: list) -> None:
    result = _gate(tmp_path, runs, {int(run["id"]): _green() for run in runs})
    assert result.returncode != 0
    assert "No push-triggered .github/workflows/security.yml run on main exists" in result.stderr
    assert not (tmp_path / "gh-stub/calls.log").read_text(encoding="utf-8").count("/jobs?")


@pytest.mark.parametrize("status", ["in_progress", "queued", "waiting", "requested", "pending"])
def test_in_progress_push_run_fails_closed(tmp_path: Path, status: str) -> None:
    result = _gate(tmp_path, [_run(800, status=status)], {800: _green()})
    assert result.returncode != 0
    assert "not completed" in result.stderr


# --- Required-job evaluation inside the selected run ------------------------


def test_missing_required_job_fails_closed(tmp_path: Path) -> None:
    result = _gate(tmp_path, [_run(800)], {800: _jobs(names=REQUIRED[:-1])})
    assert result.returncode != 0
    assert "have not registered yet" in result.stderr
    assert REQUIRED[-1] in result.stderr


@pytest.mark.parametrize(
    "status,conclusion",
    [
        ("completed", "failure"),
        ("completed", "cancelled"),
        ("completed", "skipped"),
        ("completed", "neutral"),
        ("completed", "timed_out"),
        ("in_progress", None),
        ("queued", None),
    ],
)
def test_required_job_must_complete_with_success(tmp_path: Path, status: str, conclusion: str | None) -> None:
    jobs = _green()
    jobs[0] = {**jobs[0], "status": status, "conclusion": conclusion}
    result = _gate(tmp_path, [_run(800)], {800: jobs})
    assert result.returncode != 0
    assert "are not complete with conclusion success" in result.stderr
    assert REQUIRED[0] in result.stderr


def test_non_required_jobs_in_the_run_are_ignored(tmp_path: Path) -> None:
    jobs = _green() + [{"id": 99, "name": "Some optional job", "status": "completed", "conclusion": "failure"}]
    result = _gate(tmp_path, [_run(800)], {800: jobs})
    assert result.returncode == 0, result.stderr


def test_hourly_maintenance_runs_never_block_or_certify(tmp_path: Path) -> None:
    runs = [
        _run(800),
        _run(810, event="schedule", path=".github/workflows/opencode-hourly-loop.yml", status="in_progress"),
        _run(820, event="schedule", path=".github/workflows/provider-catalog-sync.yml"),
    ]
    result = _gate(tmp_path, runs, {800: _green(), 810: [], 820: _jobs("failure")})
    assert result.returncode == 0, result.stderr
    assert _jobs_read_for(tmp_path) == ["800"]


@pytest.mark.parametrize("expected_json", ["[]", "", "not json", '{"a": 1}', '[""]', "[1]"])
def test_empty_or_malformed_allowlist_fails_closed(tmp_path: Path, expected_json: str) -> None:
    result = _gate(tmp_path, [_run(800)], {800: _green()}, expected_json=expected_json)
    assert result.returncode != 0
    assert "RELEASE_EXPECTED_PUSH_CHECKS must be a non-empty JSON array" in result.stderr


# --- Static contract ----------------------------------------------------------


def test_allowlist_is_exactly_the_four_required_security_jobs() -> None:
    assert tuple(json.loads(_expected_checks_json())) == REQUIRED


def test_script_binds_to_one_security_push_run_not_check_runs() -> None:
    script = GATE_PATH.read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert 'readonly required_workflow_path=".github/workflows/security.yml"' in code
    assert 'readonly required_branch="main"' in code
    assert "actions/runs?head_sha=${TARGET_SHA}&event=push&per_page=100" in code
    assert '.event == "push"' in code
    assert "jobs?filter=latest" in code
    assert "sort_by(.id, (.run_attempt // 1))" in code
    for removed in ("/check-runs", "details_url", "GITHUB_RUN_ID", '["success","skipped","neutral"]'):
        assert removed not in code, removed
    for workflow_name in ("opencode-hourly-loop", "provider-catalog-sync"):
        assert workflow_name not in code


def test_both_release_jobs_can_read_the_actions_api() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    for job in ("verify", "publish"):
        start = workflow.index(f"\n  {job}:\n")
        block = workflow[start : workflow.index("    steps:\n", start)]
        assert "      actions: read\n" in block, job


def test_no_other_workflow_declares_a_required_check_name() -> None:
    """Defence in depth next to the workflow-path filter."""
    job_name = re.compile(r"(?m)^    name: (.+)$")
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name == "security.yml":
            continue
        names = {match.strip().strip("\"'") for match in job_name.findall(path.read_text(encoding="utf-8"))}
        assert not names & set(REQUIRED), f"{path.name} reuses a required check name"
