"""Auto routing maximizes capability before minimizing trustworthy known cost.

Aligns with open PR #575: lexicographic capability first, known price second.
Unpriced metadata is never treated as free (issue #86 / FrugalGPT honesty).
Quality/Pareto selection remains a follow-up on #86 — this file does not invent
leaderboard scores.
"""

from __future__ import annotations

import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402


def _agent(
    agent_id: str,
    model: str,
    *,
    priority: int = 0,
    tags: tuple[str, ...] = ("reasoning",),
) -> ModelAgent:
    return ModelAgent(
        id=agent_id,
        model=model,
        base_url=f"mock://{agent_id}",
        priority=priority,
        tags=tags,
    )


def _selected(
    agents: list[ModelAgent],
    prices: dict[str, object],
    prompt: str = "Provide a concise status update.",
) -> tuple[str, dict]:
    orchestrator = TaskOrchestrator(agents, price_per_million=prices)
    result = orchestrator.complete([{"role": "user", "content": prompt}], mode="auto")
    assert result["mode"] == "route"
    row = result["trace"][0]
    return str(row["agent_id"]), row


def test_auto_routing_keeps_higher_capability_ahead_of_lower_cost() -> None:
    selected, _row = _selected(
        [
            _agent("a_high_quality", "high-quality-model", priority=1),
            _agent("z_low_cost", "low-cost-model", priority=0),
        ],
        {"high-quality-model": 20.0, "low-cost-model": 0.01},
    )
    assert selected == "a_high_quality"


def test_cheap_summarizer_does_not_beat_coding_worker() -> None:
    """Capability-first: a cheap summarizer must not win a coding task."""
    selected, row = _selected(
        [
            _agent("cheap_summarizer", "cheap-summary", tags=("summarization", "writing")),
            _agent("coding_worker", "coding-model", tags=("coding", "implementation")),
        ],
        {"cheap-summary": 0.01, "coding-model": 20.0},
        prompt="implement this code and debug the repository test",
    )
    assert selected == "coding_worker"
    assert row["selection_reason"]["routing_objective"] == "maximize_capability_then_minimize_known_cost"
    assert "failover_from" not in row


def test_auto_routing_minimizes_known_cost_within_maximum_capability() -> None:
    selected, row = _selected(
        [
            _agent("z_expensive_worker", "expensive-model"),
            _agent("a_economical_worker", "economical-model"),
        ],
        {"expensive-model": 12.0, "economical-model": 0.25},
    )
    assert selected == "a_economical_worker"
    assert row["selection_reason"]["price_known"] is True
    assert row["selection_reason"]["price_per_million_usd"] == 0.25


def test_auto_routing_does_not_treat_unpriced_model_as_free() -> None:
    selected, row = _selected(
        [
            _agent("z_unpriced_worker", "unpriced-model"),
            _agent("a_priced_worker", "priced-model"),
        ],
        {"priced-model": 1.0},
    )
    assert selected == "a_priced_worker"
    assert row["selection_reason"]["unpriced_model_policy"] == "unpriced_not_free"


@pytest.mark.parametrize(
    "invalid_price",
    [None, True, -1.0, math.nan, math.inf, "0.0"],
)
def test_invalid_price_metadata_is_unpriced_not_free(invalid_price: object) -> None:
    selected, _row = _selected(
        [
            _agent("z_invalid_price", "invalid-price-model"),
            _agent("a_known_price", "known-price-model"),
        ],
        {"invalid-price-model": invalid_price, "known-price-model": 2.0},
    )
    assert selected == "a_known_price"


def test_zero_price_is_a_known_price() -> None:
    selected, _row = _selected(
        [
            _agent("z_paid_worker", "paid-model"),
            _agent("a_zero_price", "zero-price-model"),
        ],
        {"paid-model": 0.01, "zero-price-model": 0.0},
    )
    assert selected == "a_zero_price"


def test_policy_snapshot_discloses_lexicographic_objective() -> None:
    policy = TaskOrchestrator([_agent("single_worker", "single-model")]).policy.as_dict()
    assert policy["routing_objective"] == "maximize_capability_then_minimize_known_cost"
    assert policy["unpriced_model_policy"] == "unpriced_not_free"


if __name__ == "__main__":  # pragma: no cover
    test_auto_routing_keeps_higher_capability_ahead_of_lower_cost()
    test_cheap_summarizer_does_not_beat_coding_worker()
    test_auto_routing_minimizes_known_cost_within_maximum_capability()
    test_auto_routing_does_not_treat_unpriced_model_as_free()
    test_zero_price_is_a_known_price()
    test_policy_snapshot_discloses_lexicographic_objective()
    print("ok")
