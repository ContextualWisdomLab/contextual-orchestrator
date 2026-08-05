"""Integration tests for the idempotent reasoning-control runtime extension."""

from contextual_orchestrator.reasoning_control import ReasoningDecision, ReasoningPolicy
from contextual_orchestrator.reasoning_runtime import (
    agent_reasoning_profile,
    current_reasoning_decision,
    orchestrator_reasoning_policy,
    reasoning_override,
)
from reasoning_fakes import FakeAgent, common_profile, make_orchestrator

def test_agent_configuration_round_trip_preserves_reasoning_profile() -> None:
    agent = FakeAgent.from_dict(
        {
            "id": "worker_agent",
            "model": "worker-model",
            "reasoning_profile": common_profile().to_dict(),
        }
    )
    assert agent_reasoning_profile(agent) == common_profile()
    assert FakeAgent.from_dict(agent.to_config()).to_config() == agent.to_config()


def test_route_once_injects_payload_and_trace_evidence() -> None:
    orchestrator = make_orchestrator()
    result = orchestrator.route_once([{"role": "user", "content": "Summarize this note."}])
    assert orchestrator.client.sent[-1]["reasoning_effort"] == "low"
    assert result["trace"][0]["reasoning"]["decision"]["level"] == "low"
    assert result["trace"][0]["reasoning"]["reasoning_tokens"] == 4
    assert result["reasoning_control"]["strategy"] == "adaptive"


def test_rejected_low_effort_worker_escalates_once_and_recovers_true_answer() -> None:
    orchestrator = make_orchestrator()
    result = orchestrator.conduct([{"role": "user", "content": "Calculate the answer exactly."}])
    worker = next(row for row in result["trace"] if row["role"] == "worker")
    assert result["reasoning_escalation"] == {
        "attempted": True,
        "from_level": "low",
        "to_level": "medium",
        "accepted_after_retry": True,
    }
    assert worker["output"] == "42"
    assert worker["reasoning"]["decision"]["level"] == "medium"
    assert result["answer"] == "final 42"


def test_stream_proxy_and_batch_paths_receive_reasoning_controls() -> None:
    orchestrator = make_orchestrator()
    assert "".join(orchestrator.stream_route([{"role": "user", "content": "stream"}])) == "41"
    proxy = orchestrator.proxy_completion({"input": "Research architecture"}, endpoint="responses")
    assert proxy["payload"]["reasoning"]["effort"] in {"medium", "high"}
    records = orchestrator.batch_route(["simple", "Analyze and verify architecture"])
    assert orchestrator.client.sent[-2]["reasoning_effort"] == "low"
    assert orchestrator.client.sent[-1]["reasoning_effort"] in {"medium", "high"}
    assert all("reasoning" in record["trace"][0] for record in records)


def test_caller_owned_proxy_effort_survives_orchestrator_defaults() -> None:
    orchestrator = make_orchestrator()
    proxy = orchestrator.proxy_completion(
        {"input": "complex", "reasoning": {"effort": "minimal"}},
        endpoint="responses",
    )
    assert proxy["payload"]["reasoning"]["effort"] == "minimal"


def test_reasoning_override_is_scoped_and_projected() -> None:
    orchestrator = make_orchestrator()
    decision = ReasoningDecision("high", "test", "worker", 0, ("test",))
    with reasoning_override(decision):
        assert current_reasoning_decision() is None
        orchestrator.route_once([{"role": "user", "content": "task"}])
        assert orchestrator.client.sent[-1]["reasoning_effort"] == "high"
    orchestrator.route_once([{"role": "user", "content": "task"}])
    assert orchestrator.client.sent[-1]["reasoning_effort"] == "low"


def test_policy_snapshot_and_ablation_are_machine_readable() -> None:
    orchestrator = make_orchestrator()
    assert orchestrator.policy.as_dict()["reasoning_control"]["strategy"] == "adaptive"
    report = orchestrator.run_reasoning_ablation(
        ["Calculate the answer exactly."],
        mode="conduct",
        levels=("low", "medium"),
    )
    assert [cell["level"] for cell in report["cells"]] == ["low", "medium"]
    assert report["cells"][0]["accepted_count"] == 0
    assert report["cells"][1]["accepted_count"] == 1
    assert report["cells"][0]["reasoning_tokens"] < report["cells"][1]["reasoning_tokens"]
    assert orchestrator_reasoning_policy(orchestrator).strategy == "adaptive"
