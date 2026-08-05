"""Coverage-focused edge tests for reasoning-runtime integration hooks."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterator, Mapping

import pytest

import contextual_orchestrator.reasoning_runtime as rr
from contextual_orchestrator.reasoning_control import (
    ReasoningDecision,
    ReasoningPolicy,
    ReasoningProfile,
)
from reasoning_fakes import (
    FakeAgent,
    FakeClient,
    FakeOrchestrator,
    FakePolicy,
    common_profile,
    make_orchestrator,
)

def test_retry_without_verifier_or_synthesizer_uses_escalated_worker() -> None:
    orchestrator = make_orchestrator()
    worker = orchestrator._select_agent("", "worker")
    result = {
        "answer": "41",
        "verification": {"accepted": False},
        "trace": [
            {
                "id": 0,
                "role": "worker",
                "agent_id": worker.id,
                "subtask": "calculate",
                "access": [],
                "output": "41",
                "reasoning": {
                    "decision": ReasoningDecision(
                        "low", "adaptive", "worker", 0, ("default",)
                    ).to_dict()
                },
            }
        ],
    }
    rr._retry_rejected_worker_once(orchestrator, result, "calculate")
    assert result["answer"] == "42"
    assert result["reasoning_escalation"]["accepted_after_retry"] is False


def test_retry_handles_none_usage_for_worker_verifier_and_synthesizer() -> None:
    class NoUsageClient(FakeClient):
        """Fake client that never exposes usage after a call."""

        def take_usage(self) -> None:
            return None

    agents = [
        FakeAgent("thinker_none", "m", ("thinker",)),
        FakeAgent("worker_none", "m", ("worker",)),
        FakeAgent("verifier_none", "m", ("verifier",)),
        FakeAgent("synth_none", "m", ("synthesizer",)),
    ]
    for agent in agents:
        rr.configure_agent_reasoning(agent, common_profile())
    orchestrator = FakeOrchestrator(agents, client=NoUsageClient(), reasoning_policy=ReasoningPolicy())
    result = orchestrator.conduct([{"role": "user", "content": "calculate"}])
    assert result["answer"] == "final 42"
    worker = next(row for row in result["trace"] if row["role"] == "worker")
    assert worker["reasoning"]["reasoning_tokens"] is None


def test_batch_rewriter_handles_blank_unknown_and_nonobject_rows() -> None:
    profile = common_profile()
    decisions = {"known": ReasoningDecision("medium", "x", "worker", 0, ("x",))}
    raw = (
        "\n"
        + json.dumps({"custom_id": "known", "body": {"model": "x"}})
        + "\n"
        + json.dumps({"custom_id": 3, "body": {"model": "x"}})
        + "\n"
        + json.dumps({"custom_id": "missing", "body": "not-object"})
    ).encode()
    rows = [json.loads(line) for line in rr._rewrite_batch_payload(raw, decisions, profile).decode().splitlines()]
    assert rows[0]["body"]["reasoning_effort"] == "medium"
    assert "reasoning_effort" not in rows[1]["body"]
    assert rows[2]["body"] == "not-object"


def test_installed_agent_policy_and_init_edge_branches() -> None:
    with pytest.raises((TypeError, KeyError)):
        FakeAgent.from_dict([])  # type: ignore[arg-type]
    plain = FakeAgent("no_profile", "model")
    assert "reasoning_profile" not in plain.to_config()
    assert "reasoning_control" not in FakePolicy().as_dict()

    typed = FakeOrchestrator([plain], reasoning_policy=ReasoningPolicy(strategy="disabled"))
    assert rr.orchestrator_reasoning_policy(typed).strategy == "disabled"
    mapped = FakeOrchestrator(
        [plain],
        reasoning_policy={"strategy": "fixed", "fixed_level": "low", "max_escalations": 0},
    )
    assert rr.orchestrator_reasoning_policy(mapped).strategy == "fixed"
    with pytest.raises(TypeError, match="reasoning_policy must"):
        FakeOrchestrator([plain], reasoning_policy="bad")


def test_stream_send_planner_and_model_judge_wrappers() -> None:
    orchestrator = make_orchestrator()
    worker = orchestrator._select_agent("", "worker")
    decision = ReasoningDecision("medium", "test", "worker", 0, ("test",))
    with rr._decision_scope(decision):
        assert list(orchestrator.client._stream_send(worker, {"model": "m"})) == ["stream"]
    assert orchestrator.client.sent[-1]["reasoning_effort"] == "medium"
    assert orchestrator._plan_generated("plan") == "plan"
    judged = orchestrator._model_judge_verification("42", {"reason": "base"})
    assert "reason" in judged


def test_batch_upload_without_profile_or_decisions_passes_through() -> None:
    client = FakeClient()
    plain = FakeAgent("plain_batch", "model")
    body = json.dumps({"custom_id": "x", "body": {"model": "m"}}).encode()
    client._batch_upload(plain, body)
    assert client.sent[-1] == {"model": "m"}


def test_invoke_event_usage_loop_handles_no_matching_event() -> None:
    orchestrator = make_orchestrator()
    worker = orchestrator._select_agent("", "worker")
    token = rr._EVENT_CAPTURE.set(
        [
            {
                "agent_id": "other",
                "role": "other",
                "profile": common_profile(),
                "decision": ReasoningDecision("low", "x", "other", 0, ("x",)),
                "usage": None,
            }
        ]
    )
    try:
        orchestrator._invoke(
            worker,
            [{"role": "user", "content": "x"}],
            text="x",
            role="worker",
        )
        events = rr._EVENT_CAPTURE.get()
        assert events is not None and events[0]["usage"] is None
    finally:
        rr._EVENT_CAPTURE.reset(token)


def test_ablation_empty_and_nontrace_dispatch_edges() -> None:
    orchestrator = make_orchestrator()
    with pytest.raises(ValueError, match="at least one prompt"):
        orchestrator.run_reasoning_ablation([])

    original = orchestrator._dispatch
    orchestrator._dispatch = lambda _messages, _mode: {"verification": {"accepted": False}, "trace": "bad"}
    try:
        report = orchestrator.run_reasoning_ablation(["x"], levels=("low",))
    finally:
        orchestrator._dispatch = original
    assert report["cells"][0]["total_tokens"] == 0


def test_capture_batch_and_workflow_ignore_nonlist_traces() -> None:
    orchestrator = make_orchestrator()
    records = rr._capture_batch(
        orchestrator,
        lambda _self, _prompts: [{"trace": "bad"}],
        ["x"],
    )
    assert records[0]["reasoning_control"]["strategy"] == "adaptive"




def test_retry_refreshes_downstream_reasoning_usage_evidence() -> None:
    """Recomputed verifier and synthesizer traces must expose current usage."""
    class RetryUsageClient(FakeClient):
        """Assign distinct token counts to first and second downstream calls."""

        def __init__(self) -> None:
            super().__init__()
            self.role_calls: dict[str, int] = {}

        def _send(self, agent: FakeAgent, payload: dict[str, Any]) -> str:
            """Delegate output behavior, then stamp role-specific call evidence."""
            output = super()._send(agent, payload)
            system = " ".join(
                item.get("content", "")
                for item in payload.get("messages", [])
                if item.get("role") == "system"
            )
            role = next(
                (name for name in ("verifier", "synthesizer") if f"Role: {name}" in system),
                "",
            )
            if role:
                self.role_calls[role] = self.role_calls.get(role, 0) + 1
                value = (100 if role == "verifier" else 200) + self.role_calls[role]
                self._usage = {
                    "total_tokens": value + 10,
                    "completion_tokens_details": {"reasoning_tokens": value},
                }
            return output

    agents = [
        FakeAgent("thinker_usage", "m", ("thinker",)),
        FakeAgent("worker_usage", "m", ("worker",)),
        FakeAgent("verifier_usage", "m", ("verifier",)),
        FakeAgent("synth_usage", "m", ("synthesizer",)),
    ]
    for agent in agents:
        rr.configure_agent_reasoning(agent, common_profile())
    orchestrator = FakeOrchestrator(
        agents, client=RetryUsageClient(), reasoning_policy=ReasoningPolicy()
    )
    result = orchestrator.conduct([{"role": "user", "content": "calculate"}])
    verifier = next(row for row in result["trace"] if row["role"] == "verifier")
    synthesizer = next(row for row in result["trace"] if row["role"] == "synthesizer")
    assert verifier["reasoning"]["reasoning_tokens"] == 102
    assert synthesizer["reasoning"]["reasoning_tokens"] == 202
