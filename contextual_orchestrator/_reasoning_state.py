"""Identity registries and request-local state for reasoning control."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Mapping, Sequence
import weakref

from .reasoning_control import (
    ReasoningDecision,
    ReasoningPolicy,
    ReasoningProfile,
    adapt_reasoning_decision,
    extract_reasoning_tokens,
    select_reasoning_decision,
)

class _WeakIdentityMap:
    """Weak mapping keyed by object identity rather than value equality."""

    def __init__(self) -> None:
        """Create an empty identity registry."""
        self._entries: dict[int, tuple[weakref.ReferenceType[Any], Any]] = {}

    def set(self, key: Any, value: Any) -> None:
        """Store ``value`` for one live object without equality collisions."""
        identity = id(key)

        def remove(reference: weakref.ReferenceType[Any]) -> None:
            """Remove only the entry still owned by this exact weak reference."""
            current = self._entries.get(identity)
            if current is not None and current[0] is reference:
                self._entries.pop(identity, None)

        self._entries[identity] = (weakref.ref(key, remove), value)

    def get(self, key: Any, default: Any = None) -> Any:
        """Return the value only when the stored weak reference is ``key``."""
        entry = self._entries.get(id(key))
        if entry is None:
            return default
        if entry[0]() is key:
            return entry[1]
        self._entries.pop(id(key), None)
        return default

    def pop(self, key: Any, default: Any = None) -> Any:
        """Remove and return the identity-owned entry, or ``default``."""
        entry = self._entries.get(id(key))
        if entry is None or entry[0]() is not key:
            return default
        self._entries.pop(id(key), None)
        return entry[1]


_AGENT_PROFILES = _WeakIdentityMap()
_ORCHESTRATOR_POLICIES = _WeakIdentityMap()
_POLICY_OBJECTS = _WeakIdentityMap()
_ACTIVE_DECISION: ContextVar[ReasoningDecision | None] = ContextVar(
    "contextual_orchestrator_reasoning_decision", default=None
)
_ACTIVE_POLICY: ContextVar[ReasoningPolicy | None] = ContextVar(
    "contextual_orchestrator_reasoning_policy", default=None
)
_OVERRIDE_DECISION: ContextVar[ReasoningDecision | None] = ContextVar(
    "contextual_orchestrator_reasoning_override", default=None
)
_EVENT_CAPTURE: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "contextual_orchestrator_reasoning_events", default=None
)
_BATCH_DECISIONS: ContextVar[dict[str, ReasoningDecision] | None] = ContextVar(
    "contextual_orchestrator_batch_reasoning", default=None
)


def configure_agent_reasoning(agent: Any, profile: ReasoningProfile | None) -> None:
    """Attach or remove an explicit reasoning capability profile from an agent."""
    if profile is None:
        _AGENT_PROFILES.pop(agent, None)
    elif not isinstance(profile, ReasoningProfile):
        raise TypeError("profile must be ReasoningProfile or None")
    else:
        _AGENT_PROFILES.set(agent, profile)


def agent_reasoning_profile(agent: Any) -> ReasoningProfile | None:
    """Return an agent's explicit reasoning capability profile, if configured."""
    return _AGENT_PROFILES.get(agent)


def configure_orchestrator_reasoning(orchestrator: Any, policy: ReasoningPolicy | None) -> None:
    """Attach a reasoning policy to an orchestrator and its policy snapshot object."""
    if policy is None:
        _ORCHESTRATOR_POLICIES.pop(orchestrator, None)
        current_policy = getattr(orchestrator, "policy", None)
        if current_policy is not None:
            _POLICY_OBJECTS.pop(current_policy, None)
        return
    if not isinstance(policy, ReasoningPolicy):
        raise TypeError("policy must be ReasoningPolicy or None")
    _ORCHESTRATOR_POLICIES.set(orchestrator, policy)
    current_policy = getattr(orchestrator, "policy", None)
    if current_policy is not None:
        _POLICY_OBJECTS.set(current_policy, policy)


def orchestrator_reasoning_policy(orchestrator: Any) -> ReasoningPolicy:
    """Return the configured policy or the default adaptive policy."""
    return _ORCHESTRATOR_POLICIES.get(orchestrator, ReasoningPolicy())


def current_reasoning_decision() -> ReasoningDecision | None:
    """Return the decision active for the current provider call context."""
    return _ACTIVE_DECISION.get()


@contextmanager
def reasoning_override(decision: ReasoningDecision | None) -> Iterator[None]:
    """Temporarily force one canonical decision, primarily for bounded retries."""
    token = _OVERRIDE_DECISION.set(decision)
    try:
        yield
    finally:
        _OVERRIDE_DECISION.reset(token)


@contextmanager
def _decision_scope(decision: ReasoningDecision | None) -> Iterator[None]:
    """Make a decision visible to nested provider-payload hooks."""
    token = _ACTIVE_DECISION.set(decision)
    try:
        yield
    finally:
        _ACTIVE_DECISION.reset(token)


def _message_text(messages: Sequence[Mapping[str, Any]]) -> str:
    """Return the latest user text from a chat message sequence."""
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            return message["content"]
    return ""


def _input_text(payload: Mapping[str, Any]) -> str:
    """Extract bounded selection text from chat or Responses payloads."""
    messages = payload.get("messages")
    if isinstance(messages, list):
        return _message_text([item for item in messages if isinstance(item, Mapping)])
    value = payload.get("input")
    if isinstance(value, str):
        return value
    parts: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                content = item.get("content")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    for chunk in content:
                        if isinstance(chunk, Mapping) and isinstance(chunk.get("text"), str):
                            parts.append(chunk["text"])
    return " ".join(parts)


def _infer_role(messages: Sequence[Mapping[str, Any]], fallback: str = "worker") -> str:
    """Infer an orchestration role from the repository's system-prompt contract."""
    for message in messages:
        if message.get("role") != "system" or not isinstance(message.get("content"), str):
            continue
        content = message["content"]
        for role in ("thinker", "worker", "verifier", "synthesizer"):
            if f"Role: {role}" in content or f"role={role}" in content:
                return role
    return fallback


def _resolve_decision(agent: Any, task: str, role: str) -> ReasoningDecision | None:
    """Resolve override, active decision, or policy selection for one agent."""
    profile = agent_reasoning_profile(agent)
    override = _OVERRIDE_DECISION.get()
    if override is not None:
        return adapt_reasoning_decision(profile, override)
    active = _ACTIVE_DECISION.get()
    if active is not None:
        return adapt_reasoning_decision(profile, active)
    policy = _ACTIVE_POLICY.get() or ReasoningPolicy()
    return select_reasoning_decision(profile, policy, task, role)


def _reasoning_evidence(
    profile: ReasoningProfile,
    decision: ReasoningDecision,
    usage: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build audit evidence without retaining private intermediate reasoning content."""
    return {
        "decision": decision.to_dict(),
        "profile": {
            "preset": profile.preset,
            "supported_levels": list(profile.supported_levels),
            "maximum_level": profile.maximum_level,
        },
        "reasoning_tokens": extract_reasoning_tokens(usage),
    }


def _append_event(agent: Any, role: str, decision: ReasoningDecision | None) -> None:
    """Append one successful invocation event when workflow capture is active."""
    events = _EVENT_CAPTURE.get()
    profile = agent_reasoning_profile(agent)
    if events is not None and profile is not None and decision is not None:
        events.append(
            {
                "agent_id": getattr(agent, "id", ""),
                "role": role,
                "profile": profile,
                "decision": decision,
                "usage": None,
            }
        )


def _annotate_trace(trace: list[dict[str, Any]], events: list[dict[str, Any]]) -> None:
    """Attach each captured decision to the corresponding visible workflow step."""
    remaining = events
    for step in trace:
        role = step.get("role")
        agent_id = step.get("served_agent_id", step.get("agent_id"))
        match_index = next(
            (
                index
                for index, event in enumerate(remaining)
                if event["role"] == role and event["agent_id"] == agent_id
            ),
            None,
        )
        if match_index is None:
            match_index = next(
                (index for index, event in enumerate(remaining) if event["role"] == role),
                None,
            )
        if match_index is None:
            continue
        event = remaining.pop(match_index)
        usage = step.get("usage") if isinstance(step.get("usage"), Mapping) else event.get("usage")
        step["reasoning"] = _reasoning_evidence(event["profile"], event["decision"], usage)



__all__ = [
    "_ACTIVE_DECISION",
    "_ACTIVE_POLICY",
    "_AGENT_PROFILES",
    "_BATCH_DECISIONS",
    "_EVENT_CAPTURE",
    "_OVERRIDE_DECISION",
    "_POLICY_OBJECTS",
    "_WeakIdentityMap",
    "_annotate_trace",
    "_append_event",
    "_decision_scope",
    "_infer_role",
    "_input_text",
    "_message_text",
    "_reasoning_evidence",
    "_resolve_decision",
    "agent_reasoning_profile",
    "configure_agent_reasoning",
    "configure_orchestrator_reasoning",
    "current_reasoning_decision",
    "orchestrator_reasoning_policy",
    "reasoning_override",
]
