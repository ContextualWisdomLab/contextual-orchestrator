"""The release checks gate evaluates only the allowlisted required checks.

`scripts/ci/release_checks_gate.sh` used to require every check-run GitHub
reports for the release commit to be terminal and non-failing. Scheduled
maintenance workflows (`opencode-hourly-loop.yml`, `provider-catalog-sync.yml`)
run hourly against main's tip and attach their check-runs to that same commit,
so a failed or in-flight maintenance run could block a release even though
none of them is a required check. The gate now evaluates only the explicit
`RELEASE_EXPECTED_PUSH_CHECKS` allowlist and still fails closed when a
required check is missing, pending, or not `success`.

Executes the real, unmodified script against a stubbed `gh`.
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
RUN_ID = "999999"
PRIOR_RUN_ID = "888888"
MAINTENANCE_RUN_ID = "777777"
TARGET_SHA = "cf69dc39457829c351277aad8096c24115d3991c"

REQUIRED = (
    "Tests and package quality",
    "Property and coverage-guided fuzzing",
    "Rust workspace gate",
    "CodeQL, supply chain, and SBOM",
)
HOURLY_LOOP_JOBS = (
    "Review external PR diffs without secrets",
    "Run OpenCode maintenance agent through the local gateway",
)
CATALOG_SYNC_JOB = "Refresh provider catalog with PostgreSQL"


def _expected_checks_json() -> str:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    marker = "RELEASE_EXPECTED_PUSH_CHECKS: '"
    start = workflow.index(marker) + len(marker)
    return workflow[start : workflow.index("'", start)]


def _check(
    name: str,
    conclusion: str | None = "success",
    *,
    status: str = "completed",
    run_id: str = PRIOR_RUN_ID,
    job: int = 1,
) -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "details_url": (
            "https://github.com/ContextualWisdomLab/contextual-orchestrator/"
            f"actions/runs/{run_id}/job/{job}"
        ),
    }


def _required_green() -> list[dict[str, object]]:
    return [_check(name, job=index) for index, name in enumerate(REQUIRED, start=1)]


def _run_gate(
    tmp_path: Path, checks: list[dict[str, object]], expected_json: str | None = None
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    checks_path = tmp_path / "checks.json"
    checks_path.write_text(
        json.dumps([{"total_count": len(checks), "check_runs": checks}]), encoding="utf-8"
    )
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'case "$*" in *"commits/${TARGET_SHA}/check-runs"*) cat "${GH_STUB_CHECKS_JSON}";; '
        '*) echo "unexpected gh call: $*" >&2; exit 98;; esac\n',
        encoding="utf-8",
    )
    gh.chmod(0o755)
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "GITHUB_REPOSITORY": "ContextualWisdomLab/contextual-orchestrator",
            "TARGET_SHA": TARGET_SHA,
            "GITHUB_RUN_ID": RUN_ID,
            "RELEASE_EXPECTED_PUSH_CHECKS": _expected_checks_json() if expected_json is None else expected_json,
            "GH_STUB_CHECKS_JSON": str(checks_path),
        }
    )
    return subprocess.run(
        ["bash", str(GATE_PATH)], env=env, capture_output=True, text=True, check=False, timeout=30
    )


def test_allowlist_is_exactly_the_four_required_security_jobs() -> None:
    assert tuple(json.loads(_expected_checks_json())) == REQUIRED


def test_failed_hourly_maintenance_checks_do_not_block_a_release(tmp_path: Path) -> None:
    checks = _required_green() + [
        _check(HOURLY_LOOP_JOBS[0], "failure", run_id=MAINTENANCE_RUN_ID, job=20),
        _check(HOURLY_LOOP_JOBS[1], "cancelled", run_id=MAINTENANCE_RUN_ID, job=21),
        _check(CATALOG_SYNC_JOB, "timed_out", run_id=MAINTENANCE_RUN_ID, job=22),
    ]
    result = _run_gate(tmp_path, checks)
    assert result.returncode == 0, result.stderr
    assert "Ignoring non-required check-runs" in result.stdout
    for name in (*HOURLY_LOOP_JOBS, CATALOG_SYNC_JOB):
        assert name in result.stdout


def test_in_flight_maintenance_and_unknown_checks_do_not_block_a_release(tmp_path: Path) -> None:
    checks = _required_green() + [
        _check(HOURLY_LOOP_JOBS[1], None, status="in_progress", run_id=MAINTENANCE_RUN_ID, job=21),
        _check(CATALOG_SYNC_JOB, None, status="queued", run_id=MAINTENANCE_RUN_ID, job=22),
        _check("Some future optional workflow", "action_required", job=30),
    ]
    result = _run_gate(tmp_path, checks)
    assert result.returncode == 0, result.stderr


def test_non_required_checks_cannot_stand_in_for_a_missing_required_check(tmp_path: Path) -> None:
    checks = _required_green()[:-1] + [
        _check(HOURLY_LOOP_JOBS[1], job=21),
        _check(CATALOG_SYNC_JOB, job=22),
    ]
    result = _run_gate(tmp_path, checks)
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
def test_required_check_must_complete_with_success(
    tmp_path: Path, status: str, conclusion: str | None
) -> None:
    checks = _required_green()
    checks[0] = _check(REQUIRED[0], conclusion, status=status, job=1)
    result = _run_gate(tmp_path, checks)
    assert result.returncode != 0
    assert "are not complete with conclusion success" in result.stderr
    assert REQUIRED[0] in result.stderr


def test_every_run_of_a_required_name_must_succeed(tmp_path: Path) -> None:
    """A second check-run with a required name (another suite or workflow)
    that failed is never outvoted by a green one."""
    checks = _required_green() + [_check(REQUIRED[2], "failure", run_id="666666", job=40)]
    result = _run_gate(tmp_path, checks)
    assert result.returncode != 0
    assert REQUIRED[2] in result.stderr


def test_release_runs_own_checks_are_still_excluded(tmp_path: Path) -> None:
    checks = _required_green() + [
        _check("Verify release preconditions (read-only)", None, status="in_progress", run_id=RUN_ID, job=50),
        _check(REQUIRED[1], None, status="in_progress", run_id=RUN_ID, job=51),
    ]
    result = _run_gate(tmp_path, checks)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("expected_json", ["[]", "", "not json", '{"a": 1}', '[""]', "[1]"])
def test_empty_or_malformed_allowlist_fails_closed(tmp_path: Path, expected_json: str) -> None:
    result = _run_gate(tmp_path, _required_green(), expected_json=expected_json)
    assert result.returncode != 0
    assert "RELEASE_EXPECTED_PUSH_CHECKS must be a non-empty JSON array" in result.stderr


def test_script_is_allowlist_based_not_a_denylist() -> None:
    script = GATE_PATH.read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "RELEASE_EXPECTED_PUSH_CHECKS" in code
    for workflow_name in ("opencode-hourly-loop", "provider-catalog-sync", "OpenCode", "Provider catalog"):
        assert workflow_name not in code
    assert '["success","skipped","neutral"]' not in code


def test_no_other_workflow_declares_a_required_check_name() -> None:
    """A same-named job elsewhere could satisfy a missing required check."""
    job_name = re.compile(r"(?m)^    name: (.+)$")
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name == "security.yml":
            continue
        names = {match.strip().strip("\"'") for match in job_name.findall(path.read_text(encoding="utf-8"))}
        assert not names & set(REQUIRED), f"{path.name} reuses a required check name"
