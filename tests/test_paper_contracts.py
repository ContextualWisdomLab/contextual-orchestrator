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


if __name__ == "__main__":
    test_fugu_contract_fuses_fast_route_and_deep_workflow()
    test_trinity_contract_has_explicit_thinker_worker_verifier_roles()
    test_conductor_contract_uses_access_lists_to_control_context()
    print("ok")
