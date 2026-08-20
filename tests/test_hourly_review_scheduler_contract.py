"""Contract tests for the repository's one-hour central review caller."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/contextual-orchestrator-hourly-review-repair.yml"


def test_hourly_caller_uses_central_scheduler_and_target_repository() -> None:
    """Keep the hourly job on the protected, gateway-aware central path."""
    source = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "07 * * * *"' in source
    assert "  workflow_dispatch:" in source
    assert (
        "uses: ContextualWisdomLab/.github/.github/workflows/"
        "pr-review-fix-scheduler.yml@main"
    ) in source
    assert "target_repository: ContextualWisdomLab/contextual-orchestrator" in source
    assert 'max_prs: "1"' in source
    assert 'max_dispatches: "1"' in source
    assert 'retry_hours: "1"' in source
    assert "secrets: inherit" in source
    assert "COPILOT_GITHUB_TOKEN" not in source


def test_hourly_caller_does_not_cancel_an_in_flight_review() -> None:
    """Protect long-running OpenCode/Strix work from the next hourly tick."""
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "cancel-in-progress: false" in source
