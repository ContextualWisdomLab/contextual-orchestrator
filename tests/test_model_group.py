"""Measured routing contracts for equivalent model endpoints."""

from __future__ import annotations

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.model_group import ModelGroupRouter, canonical_group_name


def _agent(agent_id: str, model: str, priority: int = 0) -> ModelAgent:
    return ModelAgent(
        agent_id,
        model,
        "https://provider.example/v1",
        provider_name="provider_name",
        priority=priority,
        group_name="ox_alpha",
    )


def test_group_router_prefers_measured_success_throughput_and_snapshots() -> None:
    router = ModelGroupRouter()
    router.observe_success("slow_member", 2.0)
    router.observe_success("fast_member", 0.2)
    router.observe_failure("fast_member")

    assert router.ranked_member_ids(["slow_member", "fast_member"])[0] == "fast_member"
    assert router.snapshot()["fast_member"]["failure_count"] == 1


def test_group_router_validates_inputs_and_forgets_departed_members() -> None:
    for value, error in [(None, TypeError), ("---", ValueError), ("single", ValueError)]:
        with pytest.raises(error):
            canonical_group_name(value)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ModelGroupRouter(ewma_gain=0)

    router = ModelGroupRouter()
    assert router.member_score("unseen_member") == 0.5
    assert router.member_report("unseen_member")["success_count"] == 0
    for invalid, error in [(True, TypeError), (float("inf"), ValueError), (-1.0, ValueError)]:
        with pytest.raises(error):
            router.observe_success("member_one", invalid)
    router.register_member("member_one")
    router.register_member("member_two")
    router.observe_success("member_one", 1.0)
    router.observe_success("member_one", 0.5)
    router.forget_members({"member_one"})
    assert set(router.snapshot()) == {"member_one"}


def test_orchestrator_resolves_group_alias_and_reorders_only_its_members() -> None:
    high = _agent("openrouter_ox_alpha", "stealth/ox-alpha", priority=2)
    low = _agent("opencode_zen_ox_alpha", "openai/x-preview-f-free", priority=1)
    other = ModelAgent("other_model", "other/model", "https://other.example/v1", priority=0)
    orchestrator = TaskOrchestrator([high, low, other])

    assert canonical_group_name("ox-alpha") == "ox_alpha"
    assert orchestrator._requested_agent("ox-alpha") == high
    orchestrator._group_router.observe_failure(high.id)
    orchestrator._group_router.observe_success(low.id, 0.1)
    assert orchestrator._requested_agent("ox_alpha") == low
    assert orchestrator._ranked_agents("", "worker")[-1] == other


def test_group_ranking_keeps_role_excluded_members_after_eligible_members() -> None:
    eligible = _agent("eligible_member", "vendor/eligible")
    excluded = ModelAgent(
        "excluded_member",
        "vendor/excluded",
        "https://provider.example/v1",
        provider_exclusions=("worker",),
        group_name="ox-alpha",
    )
    orchestrator = TaskOrchestrator([eligible, excluded])
    orchestrator._group_router.observe_success(excluded.id, 0.001)

    assert orchestrator._select_agent("", "worker") == eligible


def test_model_agent_stores_canonical_group_name() -> None:
    assert _agent("canonical_member", "vendor/model").group_name == "ox_alpha"
