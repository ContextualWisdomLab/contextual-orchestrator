from __future__ import annotations

import threading
import time
from contextvars import ContextVar

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.endpoint_race import (
    EndpointAttempt,
    EndpointEquivalenceContract,
    race_first_valid,
)


def contract(**changes: object) -> EndpointEquivalenceContract:
    values = {
        "contract_id": "shared_contract",
        "model_revision": "revision_2026_08",
        "reasoning_effort_profile": "worker_medium",
        "capability_set": ("text", "image"),
        "structured_output_contract": "openai_response_v1",
        "accuracy_class": "full_precision",
        "data_residency_policy": "kr_region_only",
        "retention_policy": "zero_retention",
        "context_limit": 128_000,
        "pricing_evidence_id": "catalog_snapshot_2026_08_26",
        "hedge_eligible": True,
        "cancellation_supported": False,
        "execution_policy": "immediate_race",
    }
    values.update(changes)
    return EndpointEquivalenceContract(**values)  # type: ignore[arg-type]


def test_slow_valid_primary_loses_to_fast_valid_completion() -> None:
    release = threading.Event()

    def slow() -> str:
        release.wait(1)
        return "slow"

    outcome = race_first_valid(
        [
            EndpointAttempt("primary_endpoint", contract(), slow),
            EndpointAttempt("hedge_endpoint", contract(), lambda: "fast"),
        ],
        validate=bool,
        deadline_seconds=1,
        max_concurrency=2,
    )
    release.set()
    assert outcome.value == "fast"
    assert outcome.winner_endpoint_id == "hedge_endpoint"
    assert outcome.attempted_endpoint_ids == ("primary_endpoint", "hedge_endpoint")
    assert outcome.cancellation_outcomes == (("primary_endpoint", "safe_drain"),)


def test_fast_invalid_completion_does_not_suppress_valid_result() -> None:
    def valid() -> str:
        time.sleep(0.01)
        return "complete"

    outcome = race_first_valid(
        [
            EndpointAttempt("invalid_endpoint", contract(), lambda: ""),
            EndpointAttempt("valid_endpoint", contract(), valid),
        ],
        validate=bool,
        deadline_seconds=1,
        max_concurrency=2,
    )
    assert outcome.winner_endpoint_id == "valid_endpoint"


def test_non_equivalent_policy_fails_closed_before_any_call() -> None:
    called: list[str] = []
    with pytest.raises(ValueError, match="cannot be proven"):
        race_first_valid(
            [
                EndpointAttempt("kr_endpoint", contract(), lambda: called.append("kr")),
                EndpointAttempt(
                    "us_endpoint",
                    contract(data_residency_policy="us_region_only"),
                    lambda: called.append("us"),
                ),
            ],
            validate=lambda _: True,
            deadline_seconds=1,
            max_concurrency=2,
        )
    assert called == []


def test_deadline_is_enforced_without_publishing_late_output() -> None:
    release = threading.Event()

    def blocked() -> str:
        release.wait(1)
        return "late"

    with pytest.raises(TimeoutError, match="deadline"):
        race_first_valid(
            [
                EndpointAttempt("first_endpoint", contract(), blocked),
                EndpointAttempt("second_endpoint", contract(), blocked),
            ],
            validate=bool,
            deadline_seconds=0.01,
            max_concurrency=2,
        )
    release.set()


def test_immediate_race_rejects_capacity_that_cannot_start_every_endpoint() -> None:
    with pytest.raises(ValueError, match="concurrency capacity"):
        race_first_valid(
            [
                EndpointAttempt("first_endpoint", contract(), lambda: "first"),
                EndpointAttempt("second_endpoint", contract(), lambda: "second"),
            ],
            validate=bool,
            deadline_seconds=1,
            max_concurrency=1,
        )


def test_race_workers_receive_an_independent_copy_of_request_context() -> None:
    request_id = ContextVar("request_id", default="missing")
    request_id.set("request_123")
    observed: list[str] = []

    def call() -> str:
        observed.append(request_id.get())
        return "complete"

    race_first_valid(
        [
            EndpointAttempt("first_endpoint", contract(), call),
            EndpointAttempt("second_endpoint", contract(), call),
        ],
        validate=bool,
        deadline_seconds=1,
        max_concurrency=2,
    )
    assert observed
    assert set(observed) == {"request_123"}


@pytest.mark.parametrize(
    "changes",
    [
        {"model_revision": ""},
        {"capability_set": ()},
        {"context_limit": 0},
        {"pricing_evidence_id": ""},
    ],
)
def test_incomplete_equivalence_contract_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        contract(**changes)


def test_text_group_uses_same_complete_valid_race_boundary() -> None:
    raw_contract = dict(contract(capability_set=("text",)).__dict__)
    agents = [
        ModelAgent(
            "slow_endpoint", "provider/shared", tags=("reasoning",),
            group_name="shared_text_group", endpoint_equivalence=raw_contract,
        ),
        ModelAgent(
            "fast_endpoint", "provider/shared", tags=("reasoning",),
            group_name="shared_text_group", endpoint_equivalence=raw_contract,
        ),
    ]
    orchestrator = TaskOrchestrator(agents)

    def chat(agent: ModelAgent, _messages: list[dict], **_kwargs: object) -> str:
        if agent.id == "slow_endpoint":
            time.sleep(0.05)
        return f"completed by {agent.id}"

    orchestrator.client.chat = chat  # type: ignore[method-assign]
    result = orchestrator.route_once(
        [{"role": "user", "content": "use the declared replica group"}],
        model_name="shared-text-group",
    )
    assert result["trace"][0]["agent_id"] == "fast_endpoint"
    assert result["answer"] == "completed by fast_endpoint"


def test_text_race_preserves_request_scoped_sampling_and_token_limits() -> None:
    raw_contract = dict(contract(capability_set=("text",)).__dict__)
    agents = [
        ModelAgent(
            endpoint_id,
            "provider/shared",
            tags=("reasoning",),
            group_name="shared_text_group",
            endpoint_equivalence=raw_contract,
        )
        for endpoint_id in ("first_endpoint", "second_endpoint")
    ]
    orchestrator = TaskOrchestrator(agents)
    observed: list[dict[str, object]] = []

    def chat(_agent: ModelAgent, _messages: list[dict], **_kwargs: object) -> str:
        observed.append(orchestrator.client.request_settings_snapshot())
        return "complete"

    orchestrator.client.chat = chat  # type: ignore[method-assign]
    with orchestrator.client.request_settings(temperature=0.73, max_output_tokens=37):
        orchestrator.route_once(
            [{"role": "user", "content": "preserve my request settings"}],
            model_name="shared-text-group",
        )
    assert observed
    assert all(item["temperature"] == 0.73 for item in observed)
    assert all(item["max_output_tokens"] == 37 for item in observed)


def test_race_usage_sink_receives_completed_loser_but_not_winner() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("first_endpoint", "mock-a", tags=("reasoning",))]
    )
    emitted: list[str] = []
    orchestrator._race_usage_sink = lambda endpoint_id, _value: emitted.append(endpoint_id)
    completed, finalize = orchestrator._race_attempt_collector("text")
    completed("winner_endpoint", ("winner", "winner_endpoint", {"prompt_tokens": 1, "completion_tokens": 1}), None)
    completed("loser_endpoint", ("loser", "loser_endpoint", {"prompt_tokens": 2, "completion_tokens": 2}), None)
    finalize("winner_endpoint")
    assert emitted == ["loser_endpoint"]
