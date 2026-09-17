"""Fail-closed contract for release-critical push-check conclusions."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/release.yml"
GATE_PATH = REPOSITORY_ROOT / "scripts/ci/release_checks_gate.sh"
RUN_ID = "999999"
PRIOR_RUN_ID = "888888"
TARGET_SHA = "cf69dc39457829c351277aad8096c24115d3991c"


def _expected_checks() -> list[str]:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    marker = "RELEASE_EXPECTED_PUSH_CHECKS: '"
    start = workflow.index(marker) + len(marker)
    end = workflow.index("'", start)
    return json.loads(workflow[start:end])


def _check(name: str, conclusion: str, job: int) -> dict[str, str]:
    return {
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "details_url": (
            "https://github.com/ContextualWisdomLab/contextual-orchestrator/"
            f"actions/runs/{PRIOR_RUN_ID}/jobs/{job}"
        ),
    }


def _run_gate(tmp_path: Path, checks: list[dict[str, str]]) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    checks_path = tmp_path / "checks.json"
    checks_path.write_text(
        json.dumps([{"total_count": len(checks), "check_runs": checks}]),
        encoding="utf-8",
    )
    gh = bin_dir / "gh"
    gh.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\ncat "${GH_STUB_CHECKS_JSON}"\n',
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
            "RELEASE_EXPECTED_PUSH_CHECKS": json.dumps(_expected_checks()),
            "GH_STUB_CHECKS_JSON": str(checks_path),
        }
    )
    return subprocess.run(
        ["bash", str(GATE_PATH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_expected_push_check_must_not_be_skipped(tmp_path: Path) -> None:
    """A registered release-critical check must succeed, not merely skip."""
    expected = _expected_checks()
    checks = [_check(name, "success", index + 1) for index, name in enumerate(expected)]
    checks[1] = _check(expected[1], "skipped", 2)

    result = _run_gate(tmp_path, checks)

    assert result.returncode != 0, result.stderr
    assert expected[1] in result.stderr


def test_expected_push_check_must_not_be_neutral(tmp_path: Path) -> None:
    """A neutral release-critical check cannot certify publication readiness."""
    expected = _expected_checks()
    checks = [_check(name, "success", index + 1) for index, name in enumerate(expected)]
    checks[2] = _check(expected[2], "neutral", 3)

    result = _run_gate(tmp_path, checks)

    assert result.returncode != 0, result.stderr
    assert expected[2] in result.stderr


def test_noncritical_skipped_check_keeps_existing_acceptable_conclusion_policy(tmp_path: Path) -> None:
    """Only named release-critical checks are tightened to success-only."""
    expected = _expected_checks()
    checks = [_check(name, "success", index + 1) for index, name in enumerate(expected)]
    checks.append(_check("Documentation preview", "skipped", 10))

    result = _run_gate(tmp_path, checks)

    assert result.returncode == 0, result.stderr
