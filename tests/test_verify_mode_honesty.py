"""Buyer-facing honesty for mode=verify and request-level reasoning_effort.

A paying caller who asks for a checked judgment must not receive a rubber-stamp
accept, a rejected worker answer framed as a normal completion, or a surprise
verify bill from everyday English. Architecture notes must not claim per-role
allocation until issue #568 lands.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    TaskOrchestrator,
)
from contextual_orchestrator.orchestrator import chat_completion_response  # noqa: E402


class NeutralVerdictClient:
    """Provider double whose verifier never states accept or reject."""

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        system = messages[0]["content"] if messages else ""
        if "Role: verifier" in system:
            return "The write-up is internally consistent and mentions the requested records."
        return "worker says yes"


class RejectingVerdictClient:
    """Provider double whose verifier explicitly rejects the worker answer."""

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        system = messages[0]["content"] if messages else ""
        if "Role: verifier" in system:
            return "I reject this. The answer is unsafe and fails the adjudication."
        return "worker says yes"


class NarrowStreamClient:
    """Pre-existing stream_chat signature that does not accept reasoning_effort."""

    def chat(self, agent: ModelAgent, messages, temperature: float = 0.2) -> str:
        return "stream-compat"

    def stream_chat(self, agent: ModelAgent, messages):
        yield "hello"


def _orchestrator(client=None) -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent(id="mock_worker", model="mock-a", tags=("reasoning", "coding", "writing")),
            ModelAgent(id="mock_verifier", model="mock-b", tags=("verification", "security")),
        ],
        client=client,
    )


def test_neutral_verify_verdict_is_not_fallback_accepted() -> None:
    result = _orchestrator(NeutralVerdictClient()).complete(
        [{"role": "user", "content": "Does record B follow from record A?"}],
        mode="verify",
    )
    assert result["mode"] == "verify"
    assert result["verification"]["accepted"] is False
    assert "fallback acceptance" not in result["verification"]["reason"]


def test_rejected_verify_does_not_serve_worker_answer() -> None:
    result = _orchestrator(RejectingVerdictClient()).complete(
        [{"role": "user", "content": "Does record B follow from record A?"}],
        mode="verify",
    )
    assert result["verification"]["accepted"] is False
    assert result["answer"] != "worker says yes"
    assert "worker says yes" not in result["answer"]
    framed = chat_completion_response(result)
    assert framed["choices"][0]["message"]["content"] != "worker says yes"
    assert framed["choices"][0]["finish_reason"] != "stop" or "reject" in framed["choices"][0]["message"]["content"].lower()


def test_auto_does_not_verify_everyday_english_substrings() -> None:
    orchestrator = _orchestrator()
    for prompt in (
        "Please preview the slide.",
        "Add a checkbox to the form.",
        "Send the confirmation email.",
        "Check the logs.",
    ):
        result = orchestrator.complete([{"role": "user", "content": prompt}])
        assert result["mode"] == "route", prompt


def test_auto_still_verifies_explicit_adjudication() -> None:
    result = _orchestrator().complete([{"role": "user", "content": "Verify this answer."}])
    assert result["mode"] == "verify"


def test_architecture_note_does_not_claim_per_role_allocation() -> None:
    text = Path("docs/architecture.md").read_text(encoding="utf-8")
    assert "per-role/per-request" not in text
    assert "request-level" in text
    assert "#568" in text or "issue 568" in text.lower()


def test_chat_response_echoes_routing_decision_and_redacts_verification() -> None:
    result = {
        "mode": "verify",
        "answer": "Verification rejected the worker answer.",
        "verification": {
            "accepted": False,
            "reason": "explicit reject",
            "verifier_output": "Bearer abcdefghijklmnopqrstuvwxyz",
        },
        "routing_decision": {
            "selected_mode": "verify",
            "reason": "task_requires_bounded_independent_verification",
        },
        "reasoning_effort": {"requested": "high", "applied": "high", "status": "applied"},
        "trace": [{"agent_id": "mock_verifier", "output": "ok"}],
    }
    body = chat_completion_response(result)
    assert body["orchestration"]["routing_decision"]["selected_mode"] == "verify"
    assert body["orchestration"]["reasoning_effort"]["status"] == "applied"
    assert "abcdefghijklmnopqrstuvwxyz" not in str(body["orchestration"]["verification"])
    assert "[REDACTED]" in body["orchestration"]["verification"]["verifier_output"]


def test_batch_envelope_reports_dropped_reasoning_effort() -> None:
    coordinator = CostRoutingCoordinator(
        _orchestrator(),
        InMemoryConfigStore(),
    )
    submitted = coordinator.complete(
        [{"role": "user", "content": "bulk job please"}],
        hints={"channel": "batch"},
        reasoning_effort="high",
    )
    assert submitted["channel"] == "batch"
    assert submitted["reasoning_effort"]["requested"] == "high"
    assert submitted["reasoning_effort"]["status"] == "dropped"


def test_verify_ledger_counts_worker_and_verifier_outputs() -> None:
    coordinator = CostRoutingCoordinator(
        _orchestrator(RejectingVerdictClient()),
        InMemoryConfigStore(),
    )
    messages = [{"role": "user", "content": "Does record B follow from record A?"}]
    verified = coordinator.complete(messages, mode="verify")
    model_name = "mock-a"
    expected = sum(
        coordinator.token_counter.count_text(str(step["output"]), model_name)
        for step in verified["trace"]
    )
    public_only = coordinator.token_counter.count_text(verified["answer"], model_name)
    assert len(verified["trace"]) == 2
    assert verified["usage"]["completion_tokens"] == expected
    assert verified["usage"]["completion_tokens"] != public_only


def test_stream_route_omits_unset_reasoning_effort_kwarg() -> None:
    orchestrator = _orchestrator(NarrowStreamClient())
    chunks = list(
        orchestrator.stream_route([{"role": "user", "content": "Write one sentence."}])
    )
    assert chunks == ["hello"]


if __name__ == "__main__":
    test_neutral_verify_verdict_is_not_fallback_accepted()
    test_rejected_verify_does_not_serve_worker_answer()
    test_auto_does_not_verify_everyday_english_substrings()
    test_auto_still_verifies_explicit_adjudication()
    test_architecture_note_does_not_claim_per_role_allocation()
    test_chat_response_echoes_routing_decision_and_redacts_verification()
    test_batch_envelope_reports_dropped_reasoning_effort()
    test_verify_ledger_counts_worker_and_verifier_outputs()
    test_stream_route_omits_unset_reasoning_effort_kwarg()
    print("ok")
