"""Contract tests for the hourly pull-request-first product-development loop."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "hourly-product-development.yml"


def _workflow_text() -> str:
    """Return the workflow source after proving the scheduled contract exists."""

    assert WORKFLOW.is_file(), "hourly product-development workflow is missing"
    return WORKFLOW.read_text(encoding="utf-8")


def test_hourly_loop_is_scheduled_and_single_flight() -> None:
    """The loop runs hourly without cancelling a task that is already dispatching."""

    workflow = _workflow_text()

    assert 'cron: "47 * * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "hourly-product-development-${{ github.repository }}" in workflow
    assert "cancel-in-progress: false" in workflow


def test_hourly_loop_is_pull_request_first_and_fails_closed() -> None:
    """No development task is created while PR or task ownership is ambiguous."""

    workflow = _workflow_text()

    pull_request_gate = workflow.index("gh pr list")
    task_inventory = workflow.index("/agents/repos/${GITHUB_REPOSITORY}/tasks?per_page=100")
    assert pull_request_gate < task_inventory
    assert "reason=open_pull_request" in workflow
    assert "reason=agent_task_token_unavailable" in workflow
    assert "reason=task_inventory_unavailable" in workflow
    assert "reason=active_agent_task" in workflow
    assert '(.state // "unknown")' in workflow
    assert 'steps.gate.outputs.dispatch == \'true\'' in workflow


def test_hourly_loop_uses_the_agent_tasks_api_without_widening_repo_token() -> None:
    """Agent-task inventory and creation use the dedicated least-privilege token."""

    workflow = _workflow_text()

    assert "AGENT_TASK_TOKEN: ${{ secrets.COPILOT_GITHUB_TOKEN }}" in workflow
    assert "REPOSITORY_TOKEN: ${{ github.token }}" in workflow
    assert "X-GitHub-Api-Version: 2026-03-10" in workflow
    assert '"/agents/repos/${GITHUB_REPOSITORY}/tasks"' in workflow
    assert "create_pull_request: true" in workflow
    assert "contents: read" in workflow
    assert "pull-requests: read" in workflow
    assert "contents: write" not in workflow
    assert "pull-requests: write" not in workflow


def test_hourly_loop_prompt_preserves_commercial_and_architecture_contracts() -> None:
    """The delegated task carries the repository's non-negotiable product gates."""

    workflow = _workflow_text()

    required_prompt_terms = (
        "ContextualWisdomLab/contextual-orchestrator",
        "single highest-value buyer-visible",
        "test-first",
        "100% production statement and branch coverage",
        "100% production docstring coverage",
        "two-word-or-longer snake_case",
        "modular MSA",
        "ContextualWisdomLab/.github",
        "naruon",
        "NVIDIA_NIM_API_KEY",
        "GET /v1/models",
        "hypothetical paid cost",
        "CHANGELOG.md",
        "Semantic Versioning",
        "Figma or Product Design",
        "Do not merge, publish, release, or bypass reviews",
        "exactly one bounded pull request",
    )
    for term in required_prompt_terms:
        assert term in workflow
