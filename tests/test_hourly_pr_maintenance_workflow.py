"""Contract tests for the bounded hourly PR-maintenance dispatcher."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/hourly-pr-maintenance.yml")
DOCTORING = Path("docs/doctoring/hourly-pr-maintenance.md")
CHANGELOG = Path("CHANGELOG.md")


def _read(path: Path) -> str:
    """Read one repository contract file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_hourly_workflow_is_bounded_and_non_cancelling() -> None:
    """Schedule one bounded heartbeat without cancelling prior legitimate work."""
    workflow = _read(WORKFLOW)

    for expected in (
        '    - cron: "11 * * * *"',
        "  workflow_dispatch:",
        "  group: contextual-orchestrator-hourly-pr-maintenance",
        "  cancel-in-progress: false",
        "  contents: read",
        "    timeout-minutes: 5",
    ):
        assert expected in workflow
    assert workflow.count("  schedule:") == 1
    assert workflow.count("  workflow_dispatch:") == 1
    assert workflow.count("  cancel-in-progress: false") == 1


def test_dispatch_targets_central_policy_with_bounded_inputs() -> None:
    """Delegate policy to central .github and limit each heartbeat to one repair."""
    workflow = _read(WORKFLOW)

    for expected in (
        '"target_repository": "ContextualWisdomLab/contextual-orchestrator"',
        '"base_branch": "main"',
        '"max_prs": "100"',
        '"max_dispatches": "1"',
        '"retry_hours": "1"',
        '"event_type": $event_type',
        "https://api.github.com/repos/ContextualWisdomLab/.github/dispatches",
    ):
        assert expected in workflow
    assert '"dry_run": false' in workflow
    assert 'status_code" != "204"' in workflow


def test_dispatch_preserves_model_and_credential_boundaries() -> None:
    """Keep model keys out of the caller and preserve the established review tokens."""
    workflow = _read(WORKFLOW)

    assert "PR_REVIEW_MERGE_TOKEN" in workflow
    assert "OPENCODE_APPROVE_TOKEN" in workflow
    assert "NVIDIA_NIM_API_KEY" not in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "secrets: inherit" not in workflow
    assert "contents: write" not in workflow
    assert "pull-requests: write" not in workflow
    assert "issues: write" not in workflow


def test_doctoring_and_changelog_define_operating_contract() -> None:
    """Keep cadence, authority, failure handling, and references auditable."""
    doctoring = _read(DOCTORING)
    changelog = _read(CHANGELOG)

    for phrase in (
        "root-cause analysis",
        "remediation feasibility",
        "one-hour same-head retry floor",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "independent non-author approval",
        "repository_dispatch",
        "APA 7th references",
    ):
        assert phrase in doctoring
    assert "Hourly PR maintenance dispatcher" in changelog
