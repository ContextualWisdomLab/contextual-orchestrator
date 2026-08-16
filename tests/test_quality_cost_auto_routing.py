"""Auto routing maximizes capability before minimizing trustworthy known cost."""

from __future__ import annotations

import math

import pytest

from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator


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


def _selected_agent(
    agents: list[ModelAgent],
    prices: dict[str, object],
) -> str:
    orchestrator = TaskOrchestrator(agents, price_per_million=prices)
    result = orchestrator.complete(
        [{"role": "user", "content": "Provide a concise status update."}],
        mode="auto",
    )
    assert result["mode"] == "route"
    return str(result["trace"][0]["agent_id"])


def test_auto_routing_keeps_higher_capability_ahead_of_lower_cost() -> None:
    selected = _selected_agent(
        [
            _agent("a_high_quality", "high-quality-model", priority=1),
            _agent("z_low_cost", "low-cost-model", priority=0),
        ],
        {"high-quality-model": 20.0, "low-cost-model": 0.01},
    )
    assert selected == "a_high_quality"


def test_auto_routing_minimizes_known_cost_within_maximum_capability() -> None:
    selected = _selected_agent(
        [
            _agent("z_expensive_worker", "expensive-model"),
            _agent("a_economical_worker", "economical-model"),
        ],
        {"expensive-model": 12.0, "economical-model": 0.25},
    )
    assert selected == "a_economical_worker"


def test_auto_routing_does_not_treat_unpriced_model_as_free() -> None:
    selected = _selected_agent(
        [
            _agent("z_unpriced_worker", "unpriced-model"),
            _agent("a_priced_worker", "priced-model"),
        ],
        {"priced-model": 1.0},
    )
    assert selected == "a_priced_worker"


@pytest.mark.parametrize(
    "invalid_price",
    [None, True, -1.0, math.nan, math.inf, "0.0"],
)
def test_invalid_price_metadata_is_unpriced_not_free(invalid_price: object) -> None:
    selected = _selected_agent(
        [
            _agent("z_invalid_price", "invalid-price-model"),
            _agent("a_known_price", "known-price-model"),
        ],
        {"invalid-price-model": invalid_price, "known-price-model": 2.0},
    )
    assert selected == "a_known_price"


def test_zero_price_is_a_known_price() -> None:
    selected = _selected_agent(
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
