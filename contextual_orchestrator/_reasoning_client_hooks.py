"""Provider-client hooks for reasoning payload and batch projection."""

from __future__ import annotations

from typing import Any, Iterator

from .reasoning_control import (
    ReasoningPolicy,
    adapt_reasoning_decision,
    apply_reasoning_payload,
    select_reasoning_decision,
)
from ._reasoning_state import (
    _ACTIVE_DECISION,
    _ACTIVE_POLICY,
    _BATCH_DECISIONS,
    _append_event,
    _decision_scope,
    _infer_role,
    _input_text,
    _message_text,
    _resolve_decision,
    agent_reasoning_profile,
)
from ._reasoning_workflow import _rewrite_batch_payload


def install_client_hooks(model_client_type: type[Any]) -> None:
    """Install chat, stream, passthrough, and Batch reasoning hooks."""
    original_client_chat = model_client_type.chat
    original_client_stream_chat = model_client_type.stream_chat
    original_client_proxy_send = model_client_type.proxy_send
    original_client_batch_chat = model_client_type.batch_chat
    original_client_send = model_client_type._send
    original_client_stream_send = model_client_type._stream_send
    original_client_send_raw = model_client_type._send_raw
    original_client_batch_upload = model_client_type._batch_upload

    def client_chat(self: Any, agent: Any, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        """Keep one role-aware decision active through chat payload construction."""
        role = _infer_role(messages)
        decision = _resolve_decision(agent, _message_text(messages), role)
        with _decision_scope(decision):
            output = original_client_chat(self, agent, messages, temperature)
        _append_event(agent, role, decision)
        return output

    def client_stream_chat(
        self: Any,
        agent: Any,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
    ) -> Iterator[str]:
        """Keep one decision active until a streaming provider response completes."""
        role = _infer_role(messages)
        decision = _resolve_decision(agent, _message_text(messages), role)
        with _decision_scope(decision):
            yield from original_client_stream_chat(self, agent, messages, temperature)
        _append_event(agent, role, decision)

    def client_proxy_send(self: Any, agent: Any, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply a worker decision to full-shape chat or Responses passthrough."""
        decision = _resolve_decision(agent, _input_text(payload), "worker")
        with _decision_scope(decision):
            output = original_client_proxy_send(self, agent, endpoint, payload)
        _append_event(agent, "worker", decision)
        return output

    def client_send(self: Any, agent: Any, payload: dict[str, Any]) -> str:
        """Project the active decision into a chat-completions payload."""
        profile = agent_reasoning_profile(agent)
        decision = adapt_reasoning_decision(profile, _ACTIVE_DECISION.get())
        return original_client_send(
            self,
            agent,
            apply_reasoning_payload(payload, profile, decision, "chat/completions"),
        )

    def client_stream_send(self: Any, agent: Any, payload: dict[str, Any]) -> Iterator[str]:
        """Project the active decision into a streaming chat payload."""
        profile = agent_reasoning_profile(agent)
        decision = adapt_reasoning_decision(profile, _ACTIVE_DECISION.get())
        yield from original_client_stream_send(
            self,
            agent,
            apply_reasoning_payload(payload, profile, decision, "chat/completions"),
        )

    def client_send_raw(self: Any, agent: Any, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Project the active decision into chat or Responses passthrough payloads."""
        profile = agent_reasoning_profile(agent)
        decision = adapt_reasoning_decision(profile, _ACTIVE_DECISION.get())
        return original_client_send_raw(
            self,
            agent,
            endpoint,
            apply_reasoning_payload(payload, profile, decision, endpoint),
        )

    def client_batch_chat(
        self: Any,
        agent: Any,
        requests: dict[str, list[dict[str, str]]],
        temperature: float = 0.2,
        poll_interval: float = 5.0,
        poll_timeout: float = 3600.0,
    ) -> dict[str, dict[str, Any]]:
        """Select and retain one bounded decision for each asynchronous batch item."""
        policy = _ACTIVE_POLICY.get() or ReasoningPolicy()
        profile = agent_reasoning_profile(agent)
        decisions = {
            custom_id: decision
            for custom_id, messages in requests.items()
            if (
                decision := select_reasoning_decision(
                    profile,
                    policy,
                    _message_text(messages),
                    "worker",
                )
            )
            is not None
        }
        token = _BATCH_DECISIONS.set(decisions)
        try:
            results = original_client_batch_chat(
                self,
                agent,
                requests,
                temperature,
                poll_interval,
                poll_timeout,
            )
        finally:
            _BATCH_DECISIONS.reset(token)
        for custom_id in results:
            _append_event(agent, "worker", decisions.get(custom_id))
        return results

    def client_batch_upload(self: Any, agent: Any, payload: bytes) -> str:
        """Rewrite provider Batch JSONL immediately before the secured upload."""
        profile = agent_reasoning_profile(agent)
        decisions = _BATCH_DECISIONS.get()
        if profile is not None and decisions:
            payload = _rewrite_batch_payload(payload, decisions, profile)
        return original_client_batch_upload(self, agent, payload)


    model_client_type.chat = client_chat
    model_client_type.stream_chat = client_stream_chat
    model_client_type.proxy_send = client_proxy_send
    model_client_type.batch_chat = client_batch_chat
    model_client_type._send = client_send
    model_client_type._stream_send = client_stream_send
    model_client_type._send_raw = client_send_raw
    model_client_type._batch_upload = client_batch_upload


__all__ = ["install_client_hooks"]
