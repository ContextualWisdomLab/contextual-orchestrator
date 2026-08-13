from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402


class RecordingClient:
    def __init__(self) -> None:
        self.calls = []

    def chat(
        self, agent: ModelAgent, messages, temperature: float = 0.2, reasoning_effort: str | None = None
    ) -> str:
        self.calls.append((agent.id, messages, reasoning_effort))
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


def test_reasoning_effort_threads_to_every_provider_call_in_a_conduct_run() -> None:
    """Fugu/Conductor/TRINITY: test-time compute is a per-request knob, not fixed.

    A caller asking for ``reasoning_effort="high"`` on a conducted (multi-step)
    request expects every provider call in that request -- thinker, worker,
    verifier, synthesizer -- to carry it, not just the first one.
    """
    client = RecordingClient()
    build(client).conduct(
        [{"role": "user", "content": "Analyze, implement, verify, and synthesize."}],
        reasoning_effort="high",
    )

    assert len(client.calls) == 4
    assert all(reasoning_effort == "high" for _, _, reasoning_effort in client.calls)


def test_reasoning_effort_omitted_by_default() -> None:
    """No caller opt-in means no behavior change for providers that reject unknown fields."""
    client = RecordingClient()
    build(client).route_once([{"role": "user", "content": "Write one sentence."}])

    assert client.calls[0][2] is None


def test_verify_mode_contract_returns_worker_and_checked_verifier_trace() -> None:
    """mode="verify": one worker call + one checked verifier judgment, cheaper than conduct().

    Grounds the "adjudication" use case Fugu/Conductor/TRINITY test-time-compute
    allocation is meant to serve: a caller wanting a verified verdict on a single
    judgment without paying for the full four-step workflow.
    """
    result = build().complete(
        [{"role": "user", "content": "Does record B logically follow from record A?"}],
        mode="verify",
    )

    assert result["mode"] == "verify"
    assert [step["role"] for step in result["trace"]] == ["worker", "verifier"]
    assert result["trace"][1]["access"] == [0]
    assert "accepted" in result["verification"]


def test_verify_mode_reasoning_effort_reaches_both_calls() -> None:
    client = RecordingClient()
    build(client).route_and_verify(
        [{"role": "user", "content": "Does record B logically follow from record A?"}],
        reasoning_effort="high",
    )

    assert len(client.calls) == 2
    assert all(reasoning_effort == "high" for _, _, reasoning_effort in client.calls)


if __name__ == "__main__":  # pragma: no cover
    test_fugu_contract_fuses_fast_route_and_deep_workflow()
    test_trinity_contract_has_explicit_thinker_worker_verifier_roles()
    test_conductor_contract_uses_access_lists_to_control_context()
    test_reasoning_effort_threads_to_every_provider_call_in_a_conduct_run()
    test_reasoning_effort_omitted_by_default()
    test_verify_mode_contract_returns_worker_and_checked_verifier_trace()
    test_verify_mode_reasoning_effort_reaches_both_calls()
    print("ok")
