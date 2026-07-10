"""Model-based verifier judge — the recorded fix for term-matching false negatives.

A verifier report that *discusses* risks tripped the term matcher (observed on the
real-OpenAI generated-workflow run). With verifier_judge="model", a verifier-selected
model replies ACCEPT/REJECT; ambiguous replies or judge failures keep the term verdict.
Default "terms" is unchanged (no extra model call).
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

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self.calls += 1
        if self.calls == 3:
            return RISKY_VERIFIER_REPORT  # term matcher sees "risk"/"error" -> would reject
        if self.calls == 5:
            return self.judge_reply
        return f"step-output({self.calls})"


def _orch(judge_reply: str, judge_mode: str = "model") -> tuple[TaskOrchestrator, _ScriptedClient]:
    client = _ScriptedClient(judge_reply)
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "model-x", tags=("reasoning", "writing", "planning", "research"))],
        client=client,
    )
    orchestrator.policy = replace(orchestrator.policy, verifier_judge=judge_mode)
    return orchestrator, client


MESSAGES = [{"role": "user", "content": "design and verify the migration plan"}]


def test_terms_judge_false_negatives_on_risk_vocabulary() -> None:
    # Baseline showing the problem the model judge fixes.
    orchestrator, client = _orch("unused", judge_mode="terms")
    result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is False  # term matcher trips on "risks"/"error"
    assert client.calls == 4  # no judge call in terms mode


def test_model_judge_accept_overrides_term_false_negative() -> None:
    orchestrator, client = _orch("ACCEPT")
    result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is True
    assert result["verification"]["judge"] == "model"
    assert client.calls == 5  # exactly one extra judge call
    assert result["answer"] == "step-output(4)"  # synthesizer answers when accepted


def test_model_judge_reject_is_respected() -> None:
    orchestrator, _ = _orch("REJECT — the migration plan loses writes.")
    result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is False
    assert result["verification"]["judge"] == "model"
    assert result["answer"] == "step-output(2)"  # falls back to the worker output


def test_ambiguous_judge_reply_keeps_term_verdict() -> None:
    orchestrator, _ = _orch("well, it depends on many factors")
    result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is False  # term verdict retained
    assert "judge" not in result["verification"]


def test_judge_failure_keeps_term_verdict() -> None:
    class _FailingJudge(_ScriptedClient):
        def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
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
    orchestrator.policy = replace(orchestrator.policy, verifier_judge="model")
    result = orchestrator.conduct(MESSAGES)
    assert result["verification"]["accepted"] is False  # fallback, request not broken
    assert "judge" not in result["verification"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
