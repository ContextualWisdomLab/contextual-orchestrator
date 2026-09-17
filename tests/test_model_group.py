"""Measured routing contracts for equivalent model endpoints."""

from __future__ import annotations

import json

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator, load_agents
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


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
def test_group_router_rejects_nonpositive_or_nonfinite_latency_floor(value: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        ModelGroupRouter(min_latency_seconds=value)


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


def test_group_router_rejects_unrepresentable_throughput_before_mutation() -> None:
    """An overflowing token sample cannot partially record a success."""
    router = ModelGroupRouter()
    with pytest.raises(ValueError, match="representable"):
        router.observe_success("member_one", 1.0, output_tokens=10**10000)
    assert router.member_observation_count("member_one") == 0


def test_group_router_records_success_without_latency_evidence() -> None:
    """``latency_seconds=None`` (e.g. a shared batch call with no honest
    single-attempt timing) must still record stability/rate evidence, but
    must never seed or move the latency EWMA -- a caller with a real timed
    success afterward gets its own honest sample, not one blended with a
    duration that never described one attempt.
    """
    router = ModelGroupRouter()
    router.observe_success("member_one", None, output_tokens=40, total_tokens=100)

    report = router.member_report("member_one")
    assert report["ewma_latency_seconds"] is None
    assert report["ewma_tokens_per_second"] is None  # throughput needs a real duration too
    assert router.member_observation_count("member_one") == 1
    assert report["max_observed_rpm"] == 1
    assert report["max_observed_tpm"] == 100

    router.observe_success("member_one", 0.4)
    assert router.member_report("member_one")["ewma_latency_seconds"] == 0.4


def test_group_router_reports_peak_observed_rpm_and_provider_reported_tpm() -> None:
    """One-minute maxima use real completions and reported tokens only."""
    now = 0.0
    router = ModelGroupRouter(clock=lambda: now)

    router.observe_success("member_one", 0.2, output_tokens=40, total_tokens=100)
    now = 10.0
    router.observe_success("member_one", 0.2, output_tokens=80, total_tokens=200)
    now = 61.0
    router.observe_success("member_one", 0.2, output_tokens=160, total_tokens=400)
    now = 80.0
    router.observe_success("member_one", 0.2)

    report = router.member_report("member_one")
    assert report["max_observed_rpm"] == 2
    assert report["max_observed_tpm"] == 600
    assert report["rate_observation_window_seconds"] == 60

    router.reset_members({"member_one"})
    assert router.member_report("member_one")["max_observed_rpm"] == 0


def test_group_reassignment_discards_old_group_measurements() -> None:
    member = _agent("member_one", "vendor/model")
    orchestrator = TaskOrchestrator([member])
    orchestrator._group_router.observe_success(member.id, 0.1)

    orchestrator.patch_agent("default", member.id, {"group_name": "different_group"})

    assert orchestrator._group_router.member_report(member.id)["success_count"] == 0


def test_load_agents_accepts_sidecar_list_catalog(tmp_path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps([{"id": "catalog_agent", "model": "catalog-model"}]),
        encoding="utf-8",
    )

    assert [agent.model for agent in load_agents(str(catalog))] == ["catalog-model"]


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


def test_zdr_only_selects_only_zdr_group_members_and_default_is_unchanged() -> None:
    non_zdr = _agent("non_zdr_member", "vendor/non-zdr", priority=99)
    zdr = ModelAgent(
        "zdr_member",
        "vendor/zdr",
        "mock://local",
        provider_name="provider_name",
        tags=("privacy:zdr",),
        group_name="shared_reasoning_model",
    )
    orchestrator = TaskOrchestrator([non_zdr, zdr])

    assert orchestrator._select_agent("", "worker") == non_zdr
    with orchestrator.request_policy(True):
        assert orchestrator._select_agent("", "worker") == zdr
        with pytest.raises(ValueError, match="not configured"):
            orchestrator._requested_agent("vendor/non-zdr")
        assert orchestrator._requested_agent("shared-reasoning-model") == zdr


def test_zdr_only_filters_the_caller_supplied_model_group_array() -> None:
    orchestrator = TaskOrchestrator([_agent("configured_member", "vendor/configured")])
    non_zdr = _agent("runtime_member", "vendor/runtime")
    zdr = ModelAgent(
        "runtime_zdr_member",
        "vendor/runtime-zdr",
        "mock://local",
        provider_name="provider_name",
        tags=("privacy:zdr",),
        group_name="runtime_reasoning_model",
    )

    selected = orchestrator.select_model_group_members(
        [non_zdr, zdr],
        chat_only=False,
        zdr_only=True,
    )

    assert [agent.id for agent in selected] == [zdr.id]


def test_chat_only_filters_the_caller_supplied_media_model_array() -> None:
    orchestrator = TaskOrchestrator([_agent("configured_member", "vendor/configured")])
    video = ModelAgent(
        "runtime_video",
        "wan-3.0",
        "mock://local",
        tags=("output:video",),
    )
    text = ModelAgent(
        "runtime_text",
        "future-text-model",
        "mock://local",
        tags=("output:text",),
    )

    selected = orchestrator.select_model_group_members(
        [video, text],
        chat_only=True,
        zdr_only=False,
    )

    assert [agent.id for agent in selected] == [text.id]


def test_zdr_only_reports_when_the_caller_supplied_array_has_no_eligible_member() -> None:
    orchestrator = TaskOrchestrator([_agent("configured_member", "vendor/configured")])

    with pytest.raises(RuntimeError, match="ZDR-eligible"):
        orchestrator.select_model_group_members(
            [_agent("runtime_member", "vendor/runtime")],
            chat_only=False,
            zdr_only=True,
        )


def test_zdr_only_does_not_reinterpret_an_exact_non_zdr_model_as_its_group() -> None:
    non_zdr = _agent("non_zdr_member", "vendor/non-zdr")
    zdr = ModelAgent(
        "zdr_member",
        "vendor/zdr",
        "mock://local",
        provider_name="provider_name",
        tags=("privacy:zdr",),
        group_name="vendor_non_zdr",
    )
    orchestrator = TaskOrchestrator([non_zdr, zdr])

    with orchestrator.request_policy(True):
        with pytest.raises(ValueError, match="not configured"):
            orchestrator._requested_agent(non_zdr.model)


def test_requested_agent_rejects_a_disabled_zdr_exact_model() -> None:
    disabled = ModelAgent(
        "disabled_zdr_member",
        "vendor/disabled-zdr",
        "mock://local",
        tags=("privacy:zdr",),
        disabled=True,
    )
    orchestrator = TaskOrchestrator(
        [disabled, ModelAgent("enabled_member", "vendor/enabled")]
    )

    with orchestrator.request_policy(True):
        with pytest.raises(ValueError, match="not configured"):
            orchestrator._requested_agent(disabled.model)


def test_request_policy_requires_a_bool_and_restores_previous_scope() -> None:
    orchestrator = TaskOrchestrator([_agent("member_one", "vendor/one")])

    with pytest.raises(TypeError, match="zdr_only"):
        with orchestrator.request_policy(1):
            pass
    with orchestrator.request_policy(True):
        with orchestrator.request_policy(False):
            assert orchestrator._zdr_agent_allowed(orchestrator.agents[0]) is True
        assert orchestrator._zdr_agent_allowed(orchestrator.agents[0]) is False


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


def test_explicit_group_conduct_keeps_every_step_and_failover_inside_group() -> None:
    first = ModelAgent("first_member", "vendor/first", group_name="shared_reasoning_model")
    second = ModelAgent("second_member", "vendor/second", group_name="shared_reasoning_model")
    outsider = ModelAgent("outside_member", "vendor/outside", priority=99)
    orchestrator = TaskOrchestrator([first, second, outsider])

    result = orchestrator.complete(
        [{"role": "user", "content": "analyze, verify, and synthesize"}],
        mode="conduct",
        model_name="shared-reasoning-model",
    )

    assert result["mode"] == "conduct"
    assert {row["agent_id"] for row in result["trace"]} <= {first.id, second.id}
    assert outsider not in orchestrator._failover_candidates(first, "task", "worker")
    assert first not in orchestrator._failover_candidates(outsider, "task", "worker")


def test_model_agent_stores_canonical_group_name() -> None:
    assert _agent("canonical_member", "vendor/model").group_name == "shared_reasoning_model"


def test_group_membership_changes_reset_but_keep_candidate_measurement_rows() -> None:
    first = ModelAgent("first_member", "provider/first")
    second = ModelAgent("second_member", "provider/second")
    orchestrator = TaskOrchestrator([first, second])

    orchestrator.set_model_group("shared-model", [first.id])
    assert set(orchestrator._group_router._members) == {first.id, second.id}

    orchestrator.delete_model_group("shared-model")
    assert set(orchestrator._group_router._members) == {first.id, second.id}


@pytest.mark.parametrize(
    "capability",
    ["text", "image", "video", "speech", "transcription", "embeddings", "rerank", "audio"],
)
def test_group_selects_measured_member_for_every_model_capability(capability: str) -> None:
    tag = "embedding" if capability == "embeddings" else capability
    first = ModelAgent("first_member", "provider/first", tags=(tag,), group_name="shared_model")
    second = ModelAgent("second_member", "provider/second", tags=(tag,), group_name="shared_model")
    orchestrator = TaskOrchestrator([first, second])
    orchestrator._group_router.observe_failure(first.id)
    orchestrator._group_router.observe_success(second.id, 0.1)

    assert orchestrator.select_capability_agent(capability, "shared-model") == second
