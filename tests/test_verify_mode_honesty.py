"""Buyer-facing honesty for mode=verify and request-level reasoning_effort.

A paying caller who asks for a checked judgment must not receive a rubber-stamp
accept (`password`, `looks good`, `I have not accepted this`), a rejected
worker answer framed as a normal completion (verify or conduct), a surprise
verify bill from everyday English or Korean check-words, an unredacted Bearer
token on the SSE path, or a sync invoice that drops verifier usage. HTTP
`run()` must echo applied `reasoning_effort`. Architecture notes must not
claim per-role allocation until issue #568 lands.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    TaskOrchestrator,
)
from contextual_orchestrator.orchestrator import (  # noqa: E402
    chat_completion_chunks,
    chat_completion_response,
)


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


class ScriptedVerifierClient:
    """Provider double that returns a fixed verifier report and worker answer."""

    def __init__(self, verifier_output: str, worker_output: str = "worker says yes") -> None:
        self.verifier_output = verifier_output
        self.worker_output = worker_output

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        system = messages[0]["content"] if messages else ""
        if "Role: verifier" in system:
            return self.verifier_output
        return self.worker_output


class EmptyVerifierClient:
    """Two-step verify where the verifier returns no text."""

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        system = messages[0]["content"] if messages else ""
        if "Role: verifier" in system:
            return ""
        return "worker says yes"


class SequenceClient:
    """Return scripted replies in call order for worker, verifier, then judge."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        reply = self.replies[self.calls]
        self.calls += 1
        return reply


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


def test_substring_positive_terms_do_not_rubber_stamp() -> None:
    """A verifier that mentions password or 'looks good' is not an accept verdict."""
    for report in (
        "Rotate the password before shipping this change.",
        "The write-up looks good but I did not finish the check.",
    ):
        result = _orchestrator(ScriptedVerifierClient(report)).complete(
            [{"role": "user", "content": "Does record B follow from record A?"}],
            mode="verify",
        )
        assert result["verification"]["accepted"] is False, report
        assert result["answer"] != "worker says yes", report


def test_negated_accept_is_not_a_pass() -> None:
    result = _orchestrator(ScriptedVerifierClient("I have not accepted this.")).complete(
        [{"role": "user", "content": "Does record B follow from record A?"}],
        mode="verify",
    )
    assert result["verification"]["accepted"] is False
    assert result["answer"] != "worker says yes"


def test_explicit_accept_still_passes() -> None:
    result = _orchestrator(ScriptedVerifierClient("The worker answer is accepted.")).complete(
        [{"role": "user", "content": "Does record B follow from record A?"}],
        mode="verify",
    )
    assert result["verification"]["accepted"] is True
    assert result["answer"] == "worker says yes"


def test_http_run_echoes_applied_reasoning_effort() -> None:
    coordinator = CostRoutingCoordinator(
        _orchestrator(RejectingVerdictClient()),
        InMemoryConfigStore(),
    )
    result = coordinator.complete(
        [{"role": "user", "content": "Does record B follow from record A?"}],
        mode="verify",
        reasoning_effort="high",
    )
    assert result["reasoning_effort"]["requested"] == "high"
    assert result["reasoning_effort"]["applied"] == "high"
    assert result["reasoning_effort"]["status"] == "applied"
    framed = chat_completion_response(result)
    assert framed["orchestration"]["reasoning_effort"]["status"] == "applied"


def test_stream_chunks_redact_verification_secrets() -> None:
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
    final = chat_completion_chunks(result)[-1]
    verification = final["orchestration"]["verification"]
    assert "abcdefghijklmnopqrstuvwxyz" not in str(verification)
    assert "[REDACTED]" in verification["verifier_output"]
    assert final["orchestration"]["routing_decision"]["selected_mode"] == "verify"
    assert final["orchestration"]["reasoning_effort"]["status"] == "applied"


def test_auto_does_not_verify_ambiguous_validate_judge_or_korean_check() -> None:
    orchestrator = _orchestrator()
    for prompt in (
        "Please validate the form fields.",
        "Do not judge the draft yet.",
        "일정 확인해주세요.",
        "성과 평가 요약만 적어 주세요.",
        "문서 검토 메모를 남겨 주세요.",
    ):
        result = orchestrator.complete([{"role": "user", "content": prompt}])
        assert result["mode"] == "route", prompt


def test_auto_still_verifies_korean_adjudication() -> None:
    result = _orchestrator().complete([{"role": "user", "content": "이 답변을 검증하세요."}])
    assert result["mode"] == "verify"


def test_ledger_counts_nonempty_steps_when_one_output_is_empty() -> None:
    coordinator = CostRoutingCoordinator(
        _orchestrator(EmptyVerifierClient()),
        InMemoryConfigStore(),
    )
    verified = coordinator.complete(
        [{"role": "user", "content": "Does record B follow from record A?"}],
        mode="verify",
    )
    model_name = "mock-a"
    expected = coordinator.token_counter.count_text("worker says yes", model_name)
    public_only = coordinator.token_counter.count_text(verified["answer"], model_name)
    assert len(verified["trace"]) == 2
    assert verified["trace"][1]["output"] == ""
    assert verified["usage"]["completion_tokens"] == expected
    assert verified["usage"]["completion_tokens"] != public_only


def test_ledger_prefers_step_usage_completion_tokens() -> None:
    coordinator = CostRoutingCoordinator(
        _orchestrator(),
        InMemoryConfigStore(),
    )
    counted = coordinator._completion_tokens_from_result(
        {
            "answer": "public envelope",
            "trace": [
                {"output": "short", "usage": {"completion_tokens": 40}},
                {"output": "also short", "usage": {"completion_tokens": 17}},
            ],
        },
        "mock-a",
    )
    assert counted == 57


def test_model_judge_negated_accept_does_not_override_reject() -> None:
    orchestrator = _orchestrator(
        SequenceClient(["worker says yes", "I reject this as unsafe.", "I DO NOT ACCEPT"])
    )
    orchestrator.policy = replace(orchestrator.policy, verifier_judge="model")
    result = orchestrator.complete(
        [{"role": "user", "content": "Does record B follow from record A?"}],
        mode="verify",
    )
    assert result["verification"]["accepted"] is False
    assert result["answer"] != "worker says yes"


def test_rejected_conduct_does_not_serve_worker_answer() -> None:
    result = _orchestrator(RejectingVerdictClient()).complete(
        [{"role": "user", "content": "Analyze, implement, and verify the migration."}],
        mode="conduct",
    )
    assert result["verification"]["accepted"] is False
    assert result["answer"] != "worker says yes"
    assert "worker says yes" not in result["answer"]


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
    test_substring_positive_terms_do_not_rubber_stamp()
    test_negated_accept_is_not_a_pass()
    test_explicit_accept_still_passes()
    test_http_run_echoes_applied_reasoning_effort()
    test_stream_chunks_redact_verification_secrets()
    test_auto_does_not_verify_ambiguous_validate_judge_or_korean_check()
    test_auto_still_verifies_korean_adjudication()
    test_ledger_counts_nonempty_steps_when_one_output_is_empty()
    test_ledger_prefers_step_usage_completion_tokens()
    test_model_judge_negated_accept_does_not_override_reject()
    test_rejected_conduct_does_not_serve_worker_answer()
    print("ok")
