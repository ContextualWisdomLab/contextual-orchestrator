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

def test_registry_removal_type_guards_and_default_policy() -> None:
    agent = FakeAgent("temporary_agent", "model")
    rr.configure_agent_reasoning(agent, common_profile())
    rr.configure_agent_reasoning(agent, None)
    assert rr.agent_reasoning_profile(agent) is None
    with pytest.raises(TypeError, match="ReasoningProfile"):
        rr.configure_agent_reasoning(agent, "bad")  # type: ignore[arg-type]

    orchestrator = make_orchestrator()
    rr.configure_orchestrator_reasoning(orchestrator, None)
    assert rr.orchestrator_reasoning_policy(orchestrator) == ReasoningPolicy()
    with pytest.raises(TypeError, match="ReasoningPolicy"):
        rr.configure_orchestrator_reasoning(orchestrator, "bad")  # type: ignore[arg-type]

    class NoPolicyObject:
        """Object without the core policy attribute."""

    target = NoPolicyObject()
    rr.configure_orchestrator_reasoning(target, ReasoningPolicy(strategy="disabled"))
    assert rr.orchestrator_reasoning_policy(target).strategy == "disabled"
    rr.configure_orchestrator_reasoning(target, None)


def test_text_and_role_helpers_cover_nested_responses_input() -> None:
    assert rr._message_text([{"role": "assistant", "content": "x"}]) == ""
    assert rr._input_text({"messages": [{"role": "user", "content": "chat"}, 3]}) == "chat"
    assert rr._input_text(
        {
            "input": [
                "a",
                {"content": "b"},
                {"content": [{"text": "c"}, {"image": "ignored"}]},
                4,
            ]
        }
    ) == "a b c"
    assert rr._input_text({"input": 5}) == ""
    assert rr._infer_role(
        [
            {"role": "assistant", "content": "Role: thinker"},
            {"role": "system", "content": 3},
            {"role": "system", "content": "role=verifier"},
        ]
    ) == "verifier"
    assert rr._infer_role([], "thinker") == "thinker"


def test_resolve_decision_uses_active_and_default_policy_paths() -> None:
    agent = FakeAgent("resolve_agent", "model")
    rr.configure_agent_reasoning(agent, common_profile())
    active = ReasoningDecision("high", "active", "worker", 0, ("active",))
    with rr._decision_scope(active):
        assert rr._resolve_decision(agent, "x", "worker") == active
    selected = rr._resolve_decision(agent, "x", "worker")
    assert selected is not None and selected.level == "low"
    unprofiled = FakeAgent("plain_agent", "model")
    assert rr._resolve_decision(unprofiled, "x", "worker") is None


def test_event_capture_and_trace_annotation_fallbacks() -> None:
    profiled = FakeAgent("captured_agent", "model")
    rr.configure_agent_reasoning(profiled, common_profile())
    decision = ReasoningDecision("low", "test", "worker", 0, ("test",))
    token = rr._EVENT_CAPTURE.set([])
    try:
        rr._append_event(profiled, "worker", decision)
        events = rr._EVENT_CAPTURE.get()
        assert events is not None and len(events) == 1
    finally:
        rr._EVENT_CAPTURE.reset(token)

    rr._append_event(profiled, "worker", decision)
    rr._append_event(FakeAgent("plain", "model"), "worker", decision)
    trace = [
        {"role": "worker", "agent_id": "different", "usage": "bad"},
        {"role": "unknown", "agent_id": "none"},
    ]
    rr._annotate_trace(
        trace,
        [
            {
                "agent_id": "captured_agent",
                "role": "worker",
                "profile": common_profile(),
                "decision": decision,
                "usage": {"reasoning_tokens": 2},
            }
        ],
    )
    assert trace[0]["reasoning"]["reasoning_tokens"] == 2
    assert "reasoning" not in trace[1]


def test_step_message_access_filters_invalid_indexes() -> None:
    trace = [{"output": "first"}, {"output": "second"}]
    messages = rr._step_messages(
        "task",
        {"role": "worker", "subtask": "do", "access": [-1, "bad", 0, 9]},
        trace,
    )
    assert "first" in messages[1]["content"]
    assert "second" not in messages[1]["content"]
    assert "(none)" in rr._step_messages("task", {}, trace)[1]["content"]


def test_retry_helper_returns_for_nonretryable_shapes() -> None:
    orchestrator = make_orchestrator()
    rr._retry_rejected_worker_once(orchestrator, {}, "task")
    rr._retry_rejected_worker_once(
        orchestrator,
        {"verification": {"accepted": False}, "trace": "bad"},
        "task",
    )
    rr._retry_rejected_worker_once(
        orchestrator,
        {"verification": {"accepted": False}, "trace": []},
        "task",
    )
    rr._retry_rejected_worker_once(
        orchestrator,
        {"verification": {"accepted": False}, "trace": [{"role": "worker"}]},
        "task",
    )
    rr._retry_rejected_worker_once(
        orchestrator,
        {
            "verification": {"accepted": False},
            "trace": [{"role": "worker", "reasoning": {"decision": {"level": "bad"}}}],
        },
        "task",
    )
    original_agent_lookup = orchestrator._agent
    orchestrator._agent = lambda agent_id: (_ for _ in ()).throw(KeyError(agent_id)) if agent_id == "missing" else original_agent_lookup(agent_id)
    try:
        rr._retry_rejected_worker_once(
            orchestrator,
            {
                "verification": {"accepted": False},
                "trace": [
                    {
                        "role": "worker",
                        "agent_id": "missing",
                        "reasoning": {
                            "decision": {
                                "level": "low",
                                "source": "x",
                                "complexity_score": 0,
                                "factors": ["x"],
                            }
                        },
                    }
                ],
            },
            "task",
        )
    finally:
        orchestrator._agent = original_agent_lookup
    ceiling = common_profile()
    worker = orchestrator._select_agent("", "worker")
    rr.configure_agent_reasoning(
        worker,
        ReasoningProfile(
            supported_levels=("low",),
            default_level="low",
            maximum_level="low",
        ),
    )
    rr._retry_rejected_worker_once(
        orchestrator,
        {
            "verification": {"accepted": False},
            "trace": [
                {
                    "role": "worker",
                    "agent_id": worker.id,
                    "reasoning": {
                        "decision": {
                            "level": "low",
                            "source": "x",
                            "complexity_score": 0,
                            "factors": ["x"],
                        }
                    },
                }
            ],
        },
        "task",
    )
    rr.configure_agent_reasoning(worker, ceiling)



def test_refresh_step_reasoning_without_event_is_a_noop() -> None:
    """A direct retry helper call without capture leaves the row unchanged."""
    row: dict[str, Any] = {}
    rr._refresh_step_reasoning_from_event(row, "verifier", "missing", None)
    assert row == {}
