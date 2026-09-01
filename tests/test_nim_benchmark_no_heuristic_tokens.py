"""Regression contracts for heuristic-free NIM benchmark decisions."""

import inspect

import pytest

from contextual_orchestrator import nim_benchmark as nb
from contextual_orchestrator.orchestrator import ModelAgent, ModelClient


def _agent(model: str = "vendor/model") -> ModelAgent:
    return ModelAgent(id="nim_worker", model=model)


def test_character_token_estimator_fails_closed() -> None:
    """Character length must never substitute for provider token evidence."""
    with pytest.raises(nb.BenchmarkContractError, match="heuristic token estimation"):
        nb.estimate_tokens("four characters are not token evidence")


def test_missing_provider_usage_fails_closed() -> None:
    """A successful-looking answer without complete usage is not budget evidence."""

    class MissingUsageClient(ModelClient):
        def chat(self, *args, **kwargs):  # type: ignore[override]
            return "answer"

        def take_usage(self):  # type: ignore[override]
            return None

    client = nb.EqualBudgetModelClient(
        MissingUsageClient(), total_token_budget=100, maximum_calls=1
    )
    client.chat(_agent(), [{"role": "user", "content": "question"}])
    with pytest.raises(nb.BenchmarkContractError, match="provider-reported"):
        client.take_usage()


def test_reported_usage_is_the_only_budget_authority() -> None:
    """Budget accounting must equal complete provider-reported usage exactly."""

    class ReportedUsageClient(ModelClient):
        def chat(self, *args, **kwargs):  # type: ignore[override]
            return "answer"

        def take_usage(self):  # type: ignore[override]
            return {"prompt_tokens": 7, "completion_tokens": 5}

    agent = _agent()
    client = nb.EqualBudgetModelClient(
        ReportedUsageClient(), total_token_budget=100, maximum_calls=1
    )
    client.chat(agent, [{"role": "user", "content": "question"}])
    client.take_usage()
    assert client.observed_tokens == 12
    assert client.reported_usage_by_model[agent.model] == {
        "prompt_tokens": 7,
        "completion_tokens": 5,
    }


def test_cheapest_worker_requires_componentwise_price_dominance() -> None:
    """Unknown request mix and model identity cannot break price-vector ambiguity."""
    agents = [_agent("vendor/model-b"), ModelAgent(id="nim_worker_c", model="vendor/model-c")]
    equal = {
        "scenario_version": "1",
        "scenario_status": "reviewed",
        "usd_per_million_tokens": {
            "vendor/model-b": {"input": 0.1, "output": 0.2},
            "vendor/model-c": {"input": 0.1, "output": 0.2},
        },
    }
    assert nb.cheapest_priced_agent(agents, equal) is None

    crossing = {
        "scenario_version": "1",
        "scenario_status": "reviewed",
        "usd_per_million_tokens": {
            "vendor/model-b": {"input": 0.01, "output": 0.50},
            "vendor/model-c": {"input": 0.50, "output": 0.01},
        },
    }
    assert nb.cheapest_priced_agent(agents, crossing) is None

    dominant = {
        "scenario_version": "1",
        "scenario_status": "reviewed",
        "usd_per_million_tokens": {
            "vendor/model-b": {"input": 0.05, "output": 0.10},
            "vendor/model-c": {"input": 0.10, "output": 0.20},
        },
    }
    assert nb.cheapest_priced_agent(agents, dominant).model == "vendor/model-b"


def test_fixed_sample_and_completion_floors_cannot_authorize_evidence() -> None:
    """Hand-selected sample-size/completion cutoffs are not statistical sufficiency proof."""
    cells: list[dict[str, object]] = []
    for task_index in range(30):
        task_id = f"task_{task_index}"
        for policy_name in ("route_once", "conduct_bounded"):
            cells.append(
                {
                    "policy_name": policy_name,
                    "task_id": task_id,
                    "run_outcome": "success",
                }
            )

    summary = nb._evaluation_evidence_summary(cells, 30)
    assert summary["evidence_status"] == "measurement_evidence_only"
    assert summary["decision_use"] == "measurement_evidence_only"
    assert summary["minimum_paired_task_count"] is None
    assert summary["required_completion_fraction"] is None
    assert summary["routing_recommendation"] is None


def test_output_token_allocation_has_no_hand_selected_default() -> None:
    """A historical dry-run margin must not silently allocate test-time compute."""
    parameter = inspect.signature(nb.run_benchmark).parameters["max_output_tokens"]
    assert parameter.default is None
