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


class PasswordSubstringClient:
    """Verifier discusses a password reset; must not match the old ``pass`` needle."""

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        system = messages[0]["content"] if messages else ""
        if "Role: verifier" in system:
            return "I read the worker write-up about the password reset flow."
        return "Use this password: hunter2 looks good"


class LooksGoodClient:
    """Everyday praise is not an accept verdict."""

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        system = messages[0]["content"] if messages else ""
        if "Role: verifier" in system:
            return "The write-up looks good overall."
        return "secret worker payload"


class NegatedAcceptClient:
    """A refused accept must not count as an accept."""

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        system = messages[0]["content"] if messages else ""
        if "Role: verifier" in system:
            return "I have not accepted this answer."
        return "secret worker payload"


class ConductRejectingClient:
    """Conduct path whose verifier rejects and whose worker text is unique."""

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        system = messages[0]["content"] if messages else ""
        if "Role: verifier" in system:
            return "I reject this. The answer is unsafe and fails the adjudication."
        if "Role: worker" in system:
            return "conduct worker secret"
        return f"{agent.id} supporting step"


class ConductSynthesizerCopiesWorkerClient:
    """Rejected conduct must not serve a synthesizer that repeats the worker."""

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        system = messages[0]["content"] if messages else ""
        if "Role: verifier" in system:
            return "REJECT\nThe worker leaked a secret and fails the adjudication."
        if "Role: worker" in system:
            return "conduct worker secret"
        if "Role: synthesizer" in system:
            return "Final answer: conduct worker secret"
        return f"{agent.id} supporting step"


class IncidentalAcceptedClient:
    """Narrating that a password was accepted is not an accept verdict."""

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        system = messages[0]["content"] if messages else ""
        if "Role: verifier" in system:
            return "The worker correctly described how the password was accepted by the IdP."
        return "secret worker payload"


class FirstLineAcceptClient:
    """A first-line ACCEPT remains a valid explicit verdict."""

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        system = messages[0]["content"] if messages else ""
        if "Role: verifier" in system:
            return "ACCEPT\nThe password reset write-up is complete."
        return "accepted worker payload"


class EmptyVerifierLongWorkerClient:
    """Empty verifier plus a long worker must still invoice the worker tokens."""

    def chat(self, agent: ModelAgent, messages, reasoning_effort: str | None = None) -> str:
        system = messages[0]["content"] if messages else ""
        if "Role: verifier" in system:
            return ""
        return "W" * 400


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


def test_password_substring_does_not_accept_verify() -> None:
    result = _orchestrator(PasswordSubstringClient()).complete(
        [{"role": "user", "content": "Does the reset follow the policy?"}],
        mode="verify",
    )
    assert result["verification"]["accepted"] is False
    assert "hunter2" not in result["answer"]


def test_looks_good_does_not_accept_verify() -> None:
    result = _orchestrator(LooksGoodClient()).complete(
        [{"role": "user", "content": "Does record B follow from record A?"}],
        mode="verify",
    )
    assert result["verification"]["accepted"] is False
    assert "secret worker payload" not in result["answer"]


def test_negated_accept_is_a_reject() -> None:
    result = _orchestrator(NegatedAcceptClient()).complete(
        [{"role": "user", "content": "Does record B follow from record A?"}],
        mode="verify",
    )
    assert result["verification"]["accepted"] is False
    assert "secret worker payload" not in result["answer"]


def test_incidental_accepted_is_not_an_accept_verdict() -> None:
    result = _orchestrator(IncidentalAcceptedClient()).complete(
        [{"role": "user", "content": "Does the reset follow the policy?"}],
        mode="verify",
    )
    assert result["verification"]["accepted"] is False
    assert "secret worker payload" not in result["answer"]
    assert result["answer_status"] == "rejected"


def test_first_line_accept_still_serves_worker() -> None:
    result = _orchestrator(FirstLineAcceptClient()).complete(
        [{"role": "user", "content": "Does the reset follow the policy?"}],
        mode="verify",
    )
    assert result["verification"]["accepted"] is True
    assert result["answer"] == "accepted worker payload"
    assert result["answer_status"] == "accepted"


def test_auto_does_not_verify_everyday_english_substrings() -> None:
    orchestrator = _orchestrator()
    for prompt in (
        "Please preview the slide.",
        "Add a checkbox to the form.",
        "Send the confirmation email.",
        "Check the logs.",
        "Please validate the form.",
        "Don't judge me.",
        "Judge this contest.",
        "확인해주세요",
        "평가 부탁",
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
    assert "unchecked" in text
    assert "HTTP" in text and "SSE" in text


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
    result["answer_status"] = "rejected"
    body = chat_completion_response(result)
    assert body["orchestration"]["routing_decision"]["selected_mode"] == "verify"
    assert body["orchestration"]["reasoning_effort"]["status"] == "applied"
    assert body["orchestration"]["answer_status"] == "rejected"
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


def test_persisted_run_echoes_applied_reasoning_effort() -> None:
    record = _orchestrator().run(
        [{"role": "user", "content": "Write one sentence."}],
        mode="route",
        reasoning_effort="high",
    )
    assert record["reasoning_effort"]["requested"] == "high"
    assert record["reasoning_effort"]["status"] == "applied"


def test_persisted_run_echoes_rejected_answer_status() -> None:
    record = _orchestrator(RejectingVerdictClient()).run(
        [{"role": "user", "content": "Does record B follow from record A?"}],
        mode="verify",
    )
    assert record["answer_status"] == "rejected"
    assert "worker says yes" not in record["answer"]


def test_complete_verify_http_echoes_produced_answer_status() -> None:
    result = _orchestrator(RejectingVerdictClient()).complete(
        [{"role": "user", "content": "Does record B follow from record A?"}],
        mode="verify",
    )
    body = chat_completion_response(result)
    assert body["orchestration"]["answer_status"] == "rejected"
    final = chat_completion_chunks(result)[-1]
    assert final["orchestration"]["answer_status"] == "rejected"


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
    result["answer_status"] = "rejected"
    final = chat_completion_chunks(result)[-1]
    assert "abcdefghijklmnopqrstuvwxyz" not in str(final["orchestration"]["verification"])
    assert "[REDACTED]" in final["orchestration"]["verification"]["verifier_output"]
    assert final["orchestration"]["routing_decision"]["selected_mode"] == "verify"
    assert final["orchestration"]["reasoning_effort"]["status"] == "applied"
    assert final["orchestration"]["answer_status"] == "rejected"


def test_empty_verifier_ledger_still_counts_worker() -> None:
    coordinator = CostRoutingCoordinator(
        _orchestrator(EmptyVerifierLongWorkerClient()),
        InMemoryConfigStore(),
    )
    verified = coordinator.complete(
        [{"role": "user", "content": "Does record B follow from record A?"}],
        mode="verify",
    )
    model_name = "mock-a"
    worker_tokens = coordinator.token_counter.count_text("W" * 400, model_name)
    public_only = coordinator.token_counter.count_text(verified["answer"], model_name)
    assert verified["usage"]["completion_tokens"] >= worker_tokens
    assert verified["usage"]["completion_tokens"] != public_only


def test_conduct_reject_does_not_serve_worker_answer() -> None:
    result = _orchestrator(ConductRejectingClient()).complete(
        [{"role": "user", "content": "Analyze the architecture and verify the change."}],
        mode="conduct",
    )
    assert result["mode"] == "conduct"
    assert result["verification"]["accepted"] is False
    assert result["answer_status"] == "rejected"
    assert "conduct worker secret" not in result["answer"]
    assert "Verification rejected" in result["answer"]


def test_conduct_reject_does_not_serve_synthesizer_copy_of_worker() -> None:
    result = _orchestrator(ConductSynthesizerCopiesWorkerClient()).complete(
        [{"role": "user", "content": "Analyze the architecture and verify the change."}],
        mode="conduct",
    )
    assert result["mode"] == "conduct"
    assert result["verification"]["accepted"] is False
    assert result["answer_status"] == "rejected"
    assert "conduct worker secret" not in result["answer"]
    assert "Verification rejected" in result["answer"]


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
    test_password_substring_does_not_accept_verify()
    test_looks_good_does_not_accept_verify()
    test_negated_accept_is_a_reject()
    test_incidental_accepted_is_not_an_accept_verdict()
    test_first_line_accept_still_serves_worker()
    test_auto_does_not_verify_everyday_english_substrings()
    test_auto_still_verifies_explicit_adjudication()
    test_architecture_note_does_not_claim_per_role_allocation()
    test_chat_response_echoes_routing_decision_and_redacts_verification()
    test_persisted_run_echoes_applied_reasoning_effort()
    test_persisted_run_echoes_rejected_answer_status()
    test_complete_verify_http_echoes_produced_answer_status()
    test_stream_chunks_redact_verification_secrets()
    test_batch_envelope_reports_dropped_reasoning_effort()
    test_empty_verifier_ledger_still_counts_worker()
    test_conduct_reject_does_not_serve_worker_answer()
    test_conduct_reject_does_not_serve_synthesizer_copy_of_worker()
    test_verify_ledger_counts_worker_and_verifier_outputs()
    test_stream_route_omits_unset_reasoning_effort_kwarg()
    print("ok")
