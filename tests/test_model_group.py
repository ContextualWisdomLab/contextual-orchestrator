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
        group_name="shared_reasoning_model",
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
    router.reset_members({"member_one"})
    assert router.snapshot() == {}


def test_group_reassignment_discards_old_group_measurements() -> None:
    member = _agent("member_one", "vendor/model")
    orchestrator = TaskOrchestrator([member])
    orchestrator._group_router.observe_success(member.id, 0.1)

    orchestrator.patch_agent("default", member.id, {"group_name": "different_group"})

    assert orchestrator._group_router.member_report(member.id)["success_count"] == 0


def test_orchestrator_resolves_group_alias_and_reorders_only_its_members() -> None:
    high = _agent("provider_one_model", "vendor-one/model-a", priority=2)
    low = _agent("provider_two_model", "vendor-two/model-b", priority=1)
    other = ModelAgent("other_model", "other/model", "https://other.example/v1", priority=0)
    orchestrator = TaskOrchestrator([high, low, other])

    assert canonical_group_name("shared-reasoning-model") == "shared_reasoning_model"
    assert orchestrator._requested_agent("shared-reasoning-model") == high
    orchestrator._group_router.observe_failure(high.id)
    orchestrator._group_router.observe_success(low.id, 0.1)
    assert orchestrator._requested_agent("shared_reasoning_model") == low
    assert orchestrator._ranked_agents("", "worker")[-1] == other


def test_explicit_group_alias_routes_plain_completion_to_measured_member() -> None:
    first = ModelAgent("provider_one_model", "vendor-one/model-a", group_name="shared_reasoning_model")
    second = ModelAgent("provider_two_model", "vendor-two/model-b", group_name="shared_reasoning_model")
    orchestrator = TaskOrchestrator([first, second])
    orchestrator._group_router.observe_failure(first.id)
    orchestrator._group_router.observe_success(second.id, 0.1)

    result = orchestrator.complete(
        [{"role": "user", "content": "route explicitly"}],
        model_name="shared-reasoning-model",
    )

    assert result["trace"][0]["agent_id"] == second.id


def test_group_ranking_keeps_role_excluded_members_after_eligible_members() -> None:
    eligible = _agent("eligible_member", "vendor/eligible")
    excluded = ModelAgent(
        "excluded_member",
        "vendor/excluded",
        "https://provider.example/v1",
        provider_exclusions=("worker",),
        group_name="shared-reasoning-model",
    )
    orchestrator = TaskOrchestrator([eligible, excluded])
    orchestrator._group_router.observe_success(excluded.id, 0.001)

    assert orchestrator._select_agent("", "worker") == eligible


def test_model_agent_stores_canonical_group_name() -> None:
    assert _agent("canonical_member", "vendor/model").group_name == "shared_reasoning_model"
