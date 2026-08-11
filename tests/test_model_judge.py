"""Structured model-based verifier judging.

Keyword matching is deliberately rejected: verifier reports can quote risks,
use negation, or be written in another language. The judge must return an
explicit structured verdict and uncertainty must fail closed.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


RISKY_VERIFIER_REPORT = "The plan is sound overall but discusses downtime risks and error handling."


class _ScriptedClient(ModelClient):
    """Template conduct: calls 1-4 are steps (verifier = call 3); call 5 is the judge."""

    def __init__(self, judge_reply: str) -> None:
        super().__init__()
        self.judge_reply = judge_reply
        self.calls = 0

    def chat(self, agent: ModelAgent, messages: list, temperature: float | None = None) -> str:  # type: ignore[override]
        self.calls += 1
        if self.calls == 3:
            return RISKY_VERIFIER_REPORT
        if self.calls == 5:
            return self.judge_reply
        return f"step-output({self.calls})"


def _orch(judge_reply: str) -> tuple[TaskOrchestrator, _ScriptedClient]:
    client = _ScriptedClient(judge_reply)
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing", "planning", "research"))],
        client=client,
    )
    return orchestrator, client


MESSAGES = [{"role": "user", "content": "design and verify the migration plan"}]


def test_keyword_matching_never_decides() -> None:
    orchestrator, _ = _orch("unused")
    result = orchestrator._judge_verifier_output("verified and good", "planner", "worker")
    assert result["accepted"] is False
    assert "keyword matching" in result["reason"]


def test_legacy_keyword_policy_is_rejected() -> None:
    orchestrator, _ = _orch("unused")
    try:
        replace(orchestrator.policy, verifier_judge="terms")
    except ValueError as exc:
        assert "keyword-based" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("keyword-based verifier policy was accepted")


def test_structured_model_judge_accepts() -> None:
    orchestrator, client = _orch('{"decision":"ACCEPT","reason":"The report supports the answer."}')
    result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is True
    assert result["verification"]["judge"] == "model"
    assert client.calls == 5
    assert result["answer"] == "step-output(4)"


def test_structured_model_judge_rejects() -> None:
    orchestrator, _ = _orch('{"decision":"REJECT","reason":"The migration plan loses writes."}')
    result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is False
    assert result["verification"]["judge"] == "model"
    assert result["answer"] == "step-output(2)"


def test_plain_keyword_reply_is_rejected() -> None:
    orchestrator, _ = _orch("ACCEPT because the report looks fine")
    result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is False
    assert "invalid structured verdict" in result["verification"]["reason"]
    assert result["answer"] == "step-output(2)"


def test_judge_rejects_wrapped_extra_and_duplicate_json() -> None:
    for reply in (
        'prefix {"decision":"ACCEPT","reason":"valid"}',
        '{"decision":"ACCEPT","reason":"valid","extra":true}',
        '{"decision":"ACCEPT","decision":"REJECT","reason":"ambiguous"}',
    ):
        orchestrator, _ = _orch(reply)
        result = orchestrator.conduct(MESSAGES)
        assert result["verification"]["accepted"] is False
        assert "invalid structured verdict" in result["verification"]["reason"]


def test_judge_failure_fails_closed() -> None:
    class _FailingJudge(_ScriptedClient):
        def chat(self, agent: ModelAgent, messages: list, temperature: float | None = None) -> str:  # type: ignore[override]
            self.calls += 1
            if self.calls == 3:
                return RISKY_VERIFIER_REPORT
            if self.calls == 5:
                raise RuntimeError("judge provider down")
            return f"step-output({self.calls})"

    client = _FailingJudge("unused")
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing", "planning", "research"))],
        client=client,
    )
    result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is False
    assert result["verification"]["judge"] == "model"
    assert "failed closed" in result["verification"]["reason"]
    assert result["answer"] == "step-output(2)"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
