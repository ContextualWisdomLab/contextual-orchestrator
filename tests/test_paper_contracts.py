from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402


class RecordingClient:
    def __init__(self) -> None:
        self.calls = []

    def chat(self, agent: ModelAgent, messages, temperature: float = 0.2) -> str:
        self.calls.append((agent.id, messages))
        return f"{agent.id}:{len(self.calls)}"


def build(client: RecordingClient | None = None) -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation"), priority=1),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security", "review"), priority=2),
        ],
        client=client,
    )


def test_fugu_contract_fuses_fast_route_and_deep_workflow() -> None:
    orchestrator = build()

    fast = orchestrator.complete([{"role": "user", "content": "Write one sentence."}], mode="auto")
    deep = orchestrator.complete(
        [{"role": "user", "content": "Analyze the architecture, implement the code, and verify risks."}],
        mode="auto",
    )

    assert fast["mode"] == "route"
    assert deep["mode"] == "conduct"


def test_trinity_contract_has_explicit_thinker_worker_verifier_roles() -> None:
    result = build().conduct([{"role": "user", "content": "Analyze and implement a safe parser."}])

    assert ["thinker", "worker", "verifier"] == [step["role"] for step in result["trace"][:3]]


def test_conductor_contract_uses_access_lists_to_control_context() -> None:
    client = RecordingClient()
    build(client).conduct([{"role": "user", "content": "Analyze, implement, verify, and synthesize."}])

    worker_prompt = client.calls[1][1][1]["content"]
    verifier_prompt = client.calls[2][1][1]["content"]

    assert "Step 0: planner_agent:1" in worker_prompt
    assert "Step 1: builder_agent:2" not in worker_prompt
    assert "Step 0: planner_agent:1" in verifier_prompt
    assert "Step 1: builder_agent:2" in verifier_prompt


def test_fugu_contract_prefers_cheapest_equally_capable_agent() -> None:
    """Among equal capability, lower known price_per_million wins."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("pricey_agent", "model-pricey", tags=("coding",)),
            ModelAgent("cheap_agent", "model-cheap", tags=("coding",)),
        ],
        price_per_million={"model-pricey": 10.0, "model-cheap": 1.0},
    )
    result = orchestrator.route_once([{"role": "user", "content": "fix this bug"}])
    assert result["trace"][0]["agent_id"] == "cheap_agent"


def test_fugu_contract_price_is_only_a_tie_break_not_a_priority_override() -> None:
    """Capability/priority dominate price; free/cheap cannot override a better match."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("higher_priority_pricey_agent", "model-pricey", tags=("coding",), priority=5),
            ModelAgent("lower_priority_free_agent", "model-free", tags=("coding",), priority=0),
        ],
        price_per_million={"model-pricey": 50.0, "model-free": 0.0},
    )
    result = orchestrator.route_once([{"role": "user", "content": "fix this bug"}])
    assert result["trace"][0]["agent_id"] == "higher_priority_pricey_agent"


def test_fugu_contract_prefers_free_over_paid_when_equally_capable() -> None:
    """Explicit free rate (0) wins free-first tie-break; unpriced is not free."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("paid_agent", "model-paid", tags=("coding",)),
            ModelAgent("free_agent", "model-free", tags=("coding",)),
            ModelAgent("unpriced_agent", "model-unpriced", tags=("coding",)),
        ],
        price_per_million={"model-paid": 2.0, "model-free": 0.0},
    )
    result = orchestrator.route_once([{"role": "user", "content": "fix this bug"}])
    assert result["trace"][0]["agent_id"] == "free_agent"


def test_fugu_contract_prefers_priced_over_unpriced_when_equally_capable() -> None:
    """Missing price_per_million is not treated as free; known paid still ranks above it."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("unpriced_agent", "model-unpriced", tags=("coding",)),
            ModelAgent("paid_agent", "model-paid", tags=("coding",)),
        ],
        price_per_million={"model-paid": 5.0},
    )
    result = orchestrator.route_once([{"role": "user", "content": "fix this bug"}])
    assert result["trace"][0]["agent_id"] == "paid_agent"


if __name__ == "__main__":  # pragma: no cover
    test_fugu_contract_fuses_fast_route_and_deep_workflow()
    test_trinity_contract_has_explicit_thinker_worker_verifier_roles()
    test_conductor_contract_uses_access_lists_to_control_context()
    test_fugu_contract_prefers_cheapest_equally_capable_agent()
    test_fugu_contract_price_is_only_a_tie_break_not_a_priority_override()
    test_fugu_contract_prefers_free_over_paid_when_equally_capable()
    test_fugu_contract_prefers_priced_over_unpriced_when_equally_capable()
    print("ok")
