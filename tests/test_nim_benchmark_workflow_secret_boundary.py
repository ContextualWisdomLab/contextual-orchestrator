"""Static security contracts for the NIM benchmark GitHub Actions workflow.

The deterministic dry-run path validates manifests and artifacts without provider
egress.  It therefore must never receive the live NVIDIA credential.  A
separate live job may receive the credential only when the operator explicitly
selects a live manual run or the conservative monthly schedule fires.
"""

from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "nim-benchmark.yml"


def _job_block(workflow_text: str, job_name: str) -> str:
    """Return one top-level job block from a GitHub Actions workflow.

    Args:
        workflow_text: Complete workflow source text.
        job_name: Exact two-space-indented key below ``jobs``.

    Raises:
        AssertionError: If the requested job is absent or empty.
    """
    pattern = re.compile(
        rf"(?ms)^  {re.escape(job_name)}:\n(?P<body>(?:^    .*\n|^\s*$)+?)(?=^  [A-Za-z0-9_-]+:|\Z)"
    )
    match = pattern.search(workflow_text)
    assert match is not None, f"workflow must define the {job_name!r} job"
    return match.group(0)


def test_dry_run_job_never_receives_nvidia_secret() -> None:
    """Require a dedicated dry-run job with no NVIDIA secret expression."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    dry_run_job = _job_block(workflow_text, "dry_run_benchmark")

    assert "inputs.dry_run == true" in dry_run_job
    assert "--dry-run" in dry_run_job
    assert "NVIDIA_NIM_API_KEY" not in dry_run_job
    assert "secrets." not in dry_run_job


def test_live_job_owns_the_only_nvidia_secret_binding() -> None:
    """Require the live-only job to own the workflow's sole provider secret."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    live_job = _job_block(workflow_text, "live_benchmark")

    assert "github.event_name == 'schedule'" in live_job
    assert "inputs.dry_run == false" in live_job
    assert "NVIDIA_NIM_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}" in live_job
    assert workflow_text.count("secrets.NVIDIA_NIM_API_KEY") == 1
