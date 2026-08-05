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

@dataclass(frozen=True)
class EdgeAgent:
    """Fresh agent type for testing non-list workflow traces after installation."""

    id: str
    model: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EdgeAgent":
        return cls(value["id"], value["model"])

    def to_config(self) -> dict[str, Any]:
        return {"id": self.id, "model": self.model}


@dataclass(frozen=True)
class EdgePolicy:
    """Fresh policy type for isolated installer coverage."""

    def as_dict(self) -> dict[str, Any]:
        return {}


class EdgeClient:
    """Fresh client type exposing all required installer seams."""

    def chat(self, _agent: EdgeAgent, _messages: list[dict[str, str]], _temperature: float = 0.2) -> str:
        return "x"

    def stream_chat(self, _agent: EdgeAgent, _messages: list[dict[str, str]], _temperature: float = 0.2) -> Iterator[str]:
        yield "x"

    def proxy_send(self, _agent: EdgeAgent, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"endpoint": endpoint, **payload}

    def batch_chat(self, _agent: EdgeAgent, _requests: dict[str, list[dict[str, str]]], *_args: Any) -> dict[str, dict[str, Any]]:
        return {}

    def _send(self, _agent: EdgeAgent, _payload: dict[str, Any]) -> str:
        return "x"

    def _stream_send(self, _agent: EdgeAgent, _payload: dict[str, Any]) -> Iterator[str]:
        yield "x"

    def _send_raw(self, _agent: EdgeAgent, _endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        return payload

    def _batch_upload(self, _agent: EdgeAgent, _payload: bytes) -> str:
        return "file"


class EdgeOrchestrator:
    """Fresh core whose workflows intentionally return non-list trace values."""

    def __init__(self, agents: list[EdgeAgent], client: EdgeClient | None = None) -> None:
        self.agents = agents
        self.client = client or EdgeClient()
        self.policy = EdgePolicy()

    def _select_agent(self, _text: str, _role: str) -> EdgeAgent:
        return self.agents[0]

    def _agent(self, agent_id: str) -> EdgeAgent:
        if self.agents[0].id != agent_id:
            raise KeyError(agent_id)
        return self.agents[0]

    def _invoke(self, primary: EdgeAgent, _messages: list[dict[str, str]], **_kwargs: Any) -> tuple[str, str, None]:
        return "x", primary.id, None

    def route_once(self, _messages: list[dict[str, str]]) -> dict[str, Any]:
        return {"trace": "bad", "verification": {"accepted": True}}

    def conduct(self, _messages: list[dict[str, str]]) -> dict[str, Any]:
        return {"trace": "bad", "verification": {"accepted": True}}

    def stream_route(self, _messages: list[dict[str, str]], workflow_run_id: str | None = None) -> Iterator[str]:
        yield "x"

    def batch_route(self, _prompts: list[str]) -> list[dict[str, Any]]:
        return [{"trace": "bad"}]

    def proxy_completion(self, body: dict[str, Any], *, endpoint: str = "chat/completions") -> dict[str, Any]:
        return {"endpoint": endpoint, **body}

    def _plan_generated(self, _task: str) -> str:
        return "plan"

    def _model_judge_verification(self, _task: str, fallback: dict[str, Any]) -> dict[str, Any]:
        return fallback

    def _judge_verifier_output(self, *_args: Any) -> dict[str, Any]:
        return {"accepted": False}

    def _dispatch(self, messages: list[dict[str, str]], _mode: str) -> dict[str, Any]:
        return self.route_once(messages)

    def _agent_to_admin_payload(self, agent: EdgeAgent) -> dict[str, Any]:
        """Return the fake admin projection for one edge agent."""
        return {"id": agent.id, "model": agent.model}

    def patch_agent(self, _pool_id: str, agent_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Replace an edge agent while rejecting extension-only fields."""
        unknown = set(patch) - {"model"}
        if unknown:
            raise ValueError(f"unknown core patch fields: {sorted(unknown)}")
        current = self._agent(agent_id)
        replacement = EdgeAgent(current.id, str(patch.get("model", current.model)))
        self.agents = [replacement if item.id == agent_id else item for item in self.agents]
        return self._agent_to_admin_payload(replacement)


def test_fresh_installer_nonlist_workflow_and_batch_paths() -> None:
    rr.install_reasoning_control(EdgeAgent, EdgeClient, EdgeOrchestrator, EdgePolicy)
    agent = EdgeAgent("edge_agent", "edge-model")
    rr.configure_agent_reasoning(agent, common_profile())
    orchestrator = EdgeOrchestrator([agent])
    assert orchestrator.route_once([{"role": "user", "content": "x"}])["trace"] == "bad"
    assert orchestrator.conduct([{"role": "user", "content": "x"}])["trace"] == "bad"
    assert orchestrator.batch_route(["x"])[0]["trace"] == "bad"


def test_weak_identity_map_stale_and_callback_edges() -> None:
    import gc
    import weakref

    registry = rr._WeakIdentityMap()

    class Key:
        """Weak-referenceable identity-map key."""

    first = Key()
    second = Key()
    registry._entries[id(first)] = (weakref.ref(second), "stale")
    assert registry.get(first, "default") == "default"
    assert registry.pop(first, "default") == "default"

    key = Key()
    registry.set(key, "value")
    registry.pop(key)
    del key
    gc.collect()


def test_input_and_role_inner_negative_branches() -> None:
    assert rr._input_text({"input": [{"content": 3}]}) == ""
    assert rr._infer_role([{"role": "system", "content": "no recognized role"}], "worker") == "worker"


def test_retry_can_fail_over_to_unprofiled_served_agent() -> None:
    orchestrator = make_orchestrator()
    worker = orchestrator._select_agent("", "worker")
    plain = FakeAgent("unprofiled_served", "model")
    orchestrator.agents.append(plain)
    original_invoke = orchestrator._invoke
    orchestrator._invoke = lambda _agent, _messages, **_kwargs: ("42", plain.id, None)
    result = {
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
    try:
        rr._retry_rejected_worker_once(orchestrator, result, "task")
    finally:
        orchestrator._invoke = original_invoke
    assert result["answer"] == "42"
    assert result["trace"][0]["served_agent_id"] == plain.id


def test_agent_from_dict_without_profile_and_event_condition_edges() -> None:
    plain = FakeAgent.from_dict({"id": "from_dict_plain", "model": "model"})
    assert rr.agent_reasoning_profile(plain) is None

    orchestrator = make_orchestrator()
    worker = orchestrator._select_agent("", "worker")
    token = rr._EVENT_CAPTURE.set(
        [
            {
                "agent_id": "wrong_agent",
                "role": "worker",
                "profile": common_profile(),
                "decision": ReasoningDecision("low", "x", "worker", 0, ("x",)),
                "usage": None,
            },
            {
                "agent_id": worker.id,
                "role": "worker",
                "profile": common_profile(),
                "decision": ReasoningDecision("low", "x", "worker", 0, ("x",)),
                "usage": {"total_tokens": 1},
            },
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


def test_identity_cleanup_callback_with_already_removed_entry() -> None:
    registry = rr._WeakIdentityMap()

    class Key:
        """Weak-referenceable key for callback invocation."""

    key = Key()
    registry.set(key, "value")
    reference = registry._entries[id(key)][0]
    callback = reference.__callback__
    registry.pop(key)
    assert callback is not None
    callback(reference)


def test_invoke_event_loop_exhausts_without_client_generated_event() -> None:
    agent = EdgeAgent("edge_loop_agent", "model")
    rr.configure_agent_reasoning(agent, common_profile())
    orchestrator = EdgeOrchestrator([agent])
    token = rr._EVENT_CAPTURE.set(
        [
            {
                "agent_id": "wrong",
                "role": "worker",
                "profile": common_profile(),
                "decision": ReasoningDecision("low", "x", "worker", 0, ("x",)),
                "usage": None,
            },
            {
                "agent_id": agent.id,
                "role": "worker",
                "profile": common_profile(),
                "decision": ReasoningDecision("low", "x", "worker", 0, ("x",)),
                "usage": {"total_tokens": 1},
            },
        ]
    )
    try:
        orchestrator._invoke(
            agent,
            [{"role": "user", "content": "x"}],
            text="x",
            role="worker",
        )
        events = rr._EVENT_CAPTURE.get()
        assert events is not None and events[0]["usage"] is None
    finally:
        rr._EVENT_CAPTURE.reset(token)


def test_agent_patch_preserves_profile_and_admin_visibility() -> None:
    """A dataclass replacement must not silently drop its reasoning capability."""
    rr.install_reasoning_control(EdgeAgent, EdgeClient, EdgeOrchestrator, EdgePolicy)
    agent = EdgeAgent("managed_agent", "before")
    profile = common_profile()
    rr.configure_agent_reasoning(agent, profile)
    orchestrator = EdgeOrchestrator([agent])
    result = orchestrator.patch_agent("default", agent.id, {"model": "after"})
    replacement = orchestrator._agent(agent.id)
    assert replacement is not agent
    assert rr.agent_reasoning_profile(replacement) == profile
    assert result["reasoning_profile"] == profile.to_dict()


def test_agent_patch_supports_explicit_profile_updates_and_persistence() -> None:
    """Typed, mapping, removal, invalid, and persistence branches stay explicit."""
    rr.install_reasoning_control(EdgeAgent, EdgeClient, EdgeOrchestrator, EdgePolicy)
    agent = EdgeAgent("profile_patch_agent", "before")
    rr.configure_agent_reasoning(agent, common_profile())
    orchestrator = EdgeOrchestrator([agent])

    class Store:
        """Capture profile-aware re-saves after the core replaces an agent."""

        def __init__(self) -> None:
            self.saved: list[EdgeAgent] = []

        def save(self, item: EdgeAgent) -> None:
            """Record one saved replacement."""
            self.saved.append(item)

    store = Store()
    orchestrator._pool_store = store
    medium = ReasoningProfile(
        supported_levels=("low", "medium"),
        default_level="medium",
        maximum_level="medium",
    )
    mapped = orchestrator.patch_agent(
        "default", agent.id, {"model": "mapped", "reasoning_profile": medium.to_dict()}
    )
    assert mapped["reasoning_profile"] == medium.to_dict()
    assert store.saved[-1] is orchestrator._agent(agent.id)

    typed = common_profile()
    result = orchestrator.patch_agent(
        "default", agent.id, {"model": "typed", "reasoning_profile": typed}
    )
    assert result["reasoning_profile"] == typed.to_dict()

    removed = orchestrator.patch_agent(
        "default", agent.id, {"model": "plain", "reasoning_profile": None}
    )
    assert "reasoning_profile" not in removed
    assert rr.agent_reasoning_profile(orchestrator._agent(agent.id)) is None

    with pytest.raises(TypeError, match="reasoning_profile patch"):
        orchestrator.patch_agent(
            "default", agent.id, {"reasoning_profile": "invalid"}
        )
