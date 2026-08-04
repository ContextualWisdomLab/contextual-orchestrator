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
    """No development session starts while PR ownership is ambiguous."""

    workflow = _workflow_text()

    pull_request_gate = workflow.index("gh pr list")
    agent_session = workflow.index("opencode run")
    assert pull_request_gate < agent_session
    assert "reason=pull_request_inventory_unavailable" in workflow
    assert "reason=open_pull_request" in workflow
    assert "reason=nim_api_key_unavailable" in workflow
    assert 'steps.gate.outputs.dispatch == \'true\'' in workflow


def test_hourly_loop_uses_nvidia_nim_and_keeps_credentials_from_the_agent() -> None:
    """The agent authenticates to NVIDIA NIM only and never holds a GitHub token."""

    workflow = _workflow_text()

    assert "NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}" in workflow
    assert "REPOSITORY_TOKEN: ${{ github.token }}" in workflow
    assert '"baseURL": "https://integrate.api.nvidia.com/v1"' in workflow
    assert '"apiKey": "{env:NVIDIA_API_KEY}"' in workflow
    assert "persist-credentials: false" in workflow
    assert "env -u GH_TOKEN -u GITHUB_TOKEN -u REPOSITORY_TOKEN" in workflow
    assert 'OPENCODE_VERSION: "1.17.13"' in workflow
    assert "sha256sum -c -" in workflow
    assert "contents: write" in workflow
    assert "pull-requests: write" in workflow
    assert "gh pr create" in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "/agents/repos" not in workflow
    assert "gh pr merge" not in workflow


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
