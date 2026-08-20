"""Shared chat-capability classification and runtime fail-closed guards.

Provider model catalogs are heterogeneous: a model identifier may name a chat
model, embedding model, reranker, transcription model, image model, or another
endpoint family.  The helpers in this module prevent clearly non-chat model IDs
from crossing a chat-agent boundary even when an incompatible agent was persisted
before discovery filtering was introduced.
"""

from __future__ import annotations

from dataclasses import replace
from functools import wraps
import re
from typing import Any

_MODEL_TOKEN_RE = re.compile(r"[a-z0-9]+")
_NON_CHAT_EXACT_TOKENS = frozenset(
    {
        "audio",
        "bge",
        "e5",
        "embed",
        "embedding",
        "embeddings",
        "guard",
        "gte",
        "image",
        "images",
        "moderation",
        "realtime",
        "rerank",
        "reranker",
        "safety",
        "sora",
        "speech",
        "transcribe",
        "transcription",
        "tts",
        "whisper",
    }
)
_NON_CHAT_TOKEN_PREFIXES = (
    "embed",
    "moderat",
    "rerank",
    "transcrib",
)


def is_chat_compatible_model_id(model_id: str) -> bool:
    """Return whether a model identifier is eligible for a chat-agent pool.

    The classifier intentionally rejects only identifiers that clearly advertise
    a non-chat endpoint family.  Unknown identifiers remain eligible until an
    authenticated capability registry can prove more specific endpoint support.
    """
    if type(model_id) is not str:
        return False
    tokens = tuple(_MODEL_TOKEN_RE.findall(model_id.casefold()))
    if not tokens:
        return False
    for token in tokens:
        if token in _NON_CHAT_EXACT_TOKENS:
            return False
        if token.startswith(_NON_CHAT_TOKEN_PREFIXES):
            return False
    return True


def install_runtime_chat_capability_guards(
    model_client_cls: type[Any],
    task_orchestrator_cls: type[Any],
) -> None:
    """Install idempotent fail-closed guards on the existing runtime classes.

    The project keeps runtime orchestration in one large compatibility module.
    Installing the invariant here lets discovery, persisted configuration, plan
    parsing, failover, and direct client calls share one classifier without
    introducing a circular import from that compatibility module back into model
    discovery.
    """
    marker = "_chat_capability_guards_installed"
    if getattr(task_orchestrator_cls, marker, False):
        return

    original_chat = model_client_cls.chat

    @wraps(original_chat)
    def guarded_chat(self: Any, agent: Any, *args: Any, **kwargs: Any) -> Any:
        """Reject a non-chat endpoint before mock or network transport executes."""
        if not is_chat_compatible_model_id(agent.model):
            raise ValueError("model is not chat-compatible and cannot serve a chat request")
        return original_chat(self, agent, *args, **kwargs)

    model_client_cls.chat = guarded_chat

    original_ranked_agents = task_orchestrator_cls._ranked_agents

    @wraps(original_ranked_agents)
    def guarded_ranked_agents(self: Any, text: str, role: str) -> list[Any]:
        """Remove stale non-chat agents before role scoring or selection."""
        ranked = original_ranked_agents(self, text, role)
        return [agent for agent in ranked if is_chat_compatible_model_id(agent.model)]

    task_orchestrator_cls._ranked_agents = guarded_ranked_agents

    original_select_agent = task_orchestrator_cls._select_agent

    @wraps(original_select_agent)
    def guarded_select_agent(self: Any, text: str, role: str) -> Any:
        """Fail with an actionable error when no chat-compatible agent remains."""
        if not self._ranked_agents(text, role):
            raise RuntimeError(f"no chat-compatible agent available for role={role}")
        return original_select_agent(self, text, role)

    task_orchestrator_cls._select_agent = guarded_select_agent

    original_failover_candidates = task_orchestrator_cls._failover_candidates

    @wraps(original_failover_candidates)
    def guarded_failover_candidates(
        self: Any,
        primary: Any,
        text: str,
        role: str,
    ) -> list[Any]:
        """Prevent cross-agent retry from falling through to another endpoint family."""
        candidates = original_failover_candidates(self, primary, text, role)
        return [agent for agent in candidates if is_chat_compatible_model_id(agent.model)]

    task_orchestrator_cls._failover_candidates = guarded_failover_candidates

    original_parse_workflow_plan = task_orchestrator_cls._parse_workflow_plan

    @wraps(original_parse_workflow_plan)
    def guarded_parse_workflow_plan(self: Any, raw: str) -> list[Any]:
        """Reselect any stale non-chat assignment named by a generated plan."""
        steps = original_parse_workflow_plan(self, raw)
        agents_by_id = {agent.id: agent for agent in self.agents}
        guarded_steps: list[Any] = []
        for step in steps:
            assigned = agents_by_id.get(step.agent_id)
            if assigned is not None and not is_chat_compatible_model_id(assigned.model):
                replacement = self._select_agent(step.subtask, step.role)
                step = replace(step, agent_id=replacement.id)
            guarded_steps.append(step)
        return guarded_steps

    task_orchestrator_cls._parse_workflow_plan = guarded_parse_workflow_plan
    setattr(task_orchestrator_cls, marker, True)
