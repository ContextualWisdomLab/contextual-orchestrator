"""Fail-closed contracts for model selection without validated routing evidence."""

from __future__ import annotations

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator


def test_priority_cannot_select_between_ambiguous_virtual_candidates() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("high_priority", "model-a", priority=100),
            ModelAgent("low_priority", "model-b", priority=1),
        ]
    )

    with pytest.raises(RuntimeError, match="routing evidence"):
        orchestrator._ranked_agents("task", "worker")


def test_role_metadata_cannot_select_between_ambiguous_candidates() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("tag_match", "model-a", tags=("reasoning",)),
            ModelAgent("other", "model-b", tags=("coding",)),
        ]
    )

    with pytest.raises(RuntimeError, match="routing evidence"):
        orchestrator._ranked_agents("reason about this", "worker")


def test_role_exclusion_is_eligibility_not_tail_fallback() -> None:
    eligible = ModelAgent("eligible_agent", "model-a")
    excluded = ModelAgent(
        "excluded_agent", "model-b", provider_exclusions=("worker",)
    )
    orchestrator = TaskOrchestrator([excluded, eligible])

    assert orchestrator._ranked_agents("task", "worker") == [eligible]


def test_complete_exact_context_psychometric_evidence_can_order_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = ModelAgent("first_agent", "model-a")
    second = ModelAgent("second_agent", "model-b")
    orchestrator = TaskOrchestrator([first, second])
    monkeypatch.setattr(
        orchestrator._psychometric_router,
        "ranked_evidence",
        lambda agent_ids, prompt, vector: [
            ("second_agent", 0.91),
            ("first_agent", 0.63),
        ],
    )

    assert orchestrator._ranked_agents(
        "task", "worker", prompt_context="exact canonical prompt"
    ) == [second, first]


def test_partial_psychometric_evidence_cannot_demote_unmeasured_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("measured_agent", "model-a"), ModelAgent("unknown_agent", "model-b")]
    )
    monkeypatch.setattr(
        orchestrator._psychometric_router,
        "ranked_evidence",
        lambda agent_ids, prompt, vector: [("measured_agent", 0.91)],
    )

    with pytest.raises(RuntimeError, match="routing evidence"):
        orchestrator._ranked_agents(
            "task", "worker", prompt_context="exact canonical prompt"
        )


def test_duplicate_provider_deployments_need_explicit_endpoint_or_other_evidence() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("provider_one", "same-model", base_url="mock://one"),
            ModelAgent("provider_two", "same-model", base_url="mock://two"),
        ]
    )

    with pytest.raises(RuntimeError, match="multiple eligible agents"):
        orchestrator._requested_agent("same-model")
