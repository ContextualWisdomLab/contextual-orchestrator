"""Research-backed contracts for the autonomous development agent prompt."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "hourly-product-development.yml"


def _workflow_text() -> str:
    """Return the scheduled workflow source for prompt-contract assertions."""
    assert WORKFLOW.is_file(), "hourly product-development workflow is missing"
    return WORKFLOW.read_text(encoding="utf-8")


def test_agent_prompt_allocates_test_time_compute_from_primary_research() -> None:
    """Require explicit Fugu, Conductor, and TRINITY compute-allocation duties."""
    workflow = _workflow_text()

    required_terms = (
        "Fugu",
        "Conductor",
        "TRINITY",
        "recursive depth",
        "task decomposition",
        "access lists",
        "reasoning effort",
        "ablation",
        "Speed is not the primary objective",
    )
    for term in required_terms:
        assert term in workflow


def test_agent_prompt_maintains_architecture_decisions_and_keeps_working() -> None:
    """Require ADR upkeep and non-conflicting work while external gates run."""
    workflow = _workflow_text()

    required_terms = (
        "AGENTS.md",
        "CLAUDE.md",
        "ARCHITECTURE.md",
        "CHANGELOG.md",
        "checks or reviews are pending",
        "continue a non-conflicting bounded slice",
    )
    for term in required_terms:
        assert term in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
