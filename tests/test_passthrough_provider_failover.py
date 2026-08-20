"""Regression coverage for cross-provider failover on raw OpenAI passthrough."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
import urllib.error

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator


class SequencedProxyClient:
    """Record passthrough calls and return configured outcomes by agent id."""

    def __init__(self, outcomes: dict[str, dict[str, Any] | BaseException]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def proxy_send_once(
        self,
        agent: ModelAgent,
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Perform one deterministic provider attempt for the requested agent."""
        self.calls.append((agent.id, endpoint, deepcopy(payload)))
        outcome = self.outcomes[agent.id]
        if isinstance(outcome, BaseException):
            raise outcome
        return deepcopy(outcome)


def _rate_limit() -> urllib.error.HTTPError:
    """Return a realistic provider HTTP 429 error."""
    return urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions",
        429,
        "rate limited",
        None,
        None,
    )


def _build(client: SequencedProxyClient) -> TaskOrchestrator:
    """Build a deterministic two-provider pool for passthrough tests."""
    return TaskOrchestrator(
        [
            ModelAgent(
                "primary_agent",
                "primary-model",
                tags=("coding", "implementation", "security", "review"),
                priority=10,
            ),
            ModelAgent(
                "fallback_agent",
                "fallback-model",
                tags=("coding", "implementation", "security", "review"),
                priority=1,
            ),
        ],
        client=client,
    )


def test_429_advances_immediately_and_preserves_tool_request() -> None:
    """A 429 must advance to another model without replaying the saturated one."""
    client = SequencedProxyClient(
        {
            "primary_agent": _rate_limit(),
            "fallback_agent": {
                "object": "chat.completion",
                "model": "fallback-model",
                "choices": [],
            },
        }
    )
    orchestrator = _build(client)
    tools = [
        {
            "type": "function",
            "function": {"name": "inspect", "parameters": {"type": "object"}},
        }
    ]
    body = {
        "messages": [{"role": "user", "content": "review this security-sensitive code"}],
        "tools": tools,
        "tool_choice": "auto",
        "response_format": {"type": "json_object"},
        "mode": "auto",
        "stream": True,
    }
    original = deepcopy(body)

    result = orchestrator.proxy_completion(body)

    assert result["model"] == "fallback-model"
    assert [call[0] for call in client.calls] == ["primary_agent", "fallback_agent"]
    assert client.calls[0][2]["model"] == "primary-model"
    assert client.calls[1][2]["model"] == "fallback-model"
    assert client.calls[1][2]["tools"] == tools
    assert client.calls[1][2]["tool_choice"] == "auto"
    assert client.calls[1][2]["response_format"] == {"type": "json_object"}
    assert client.calls[1][2]["stream"] is False
    assert "mode" not in client.calls[1][2]
    assert body == original


def test_all_candidate_failures_chain_final_provider_error() -> None:
    """Exhausted passthrough candidates must fail closed with the final cause."""
    first = _rate_limit()
    final = RuntimeError("fallback unavailable")
    client = SequencedProxyClient(
        {"primary_agent": first, "fallback_agent": final}
    )
    orchestrator = _build(client)

    with pytest.raises(RuntimeError, match="all 2 candidate agents failed") as caught:
        orchestrator.proxy_completion(
            {
                "messages": [{"role": "user", "content": "review code"}],
                "tools": [],
            }
        )

    assert caught.value.__cause__ is final
    assert [call[0] for call in client.calls] == ["primary_agent", "fallback_agent"]


def test_cli_server_constructs_the_failover_orchestrator() -> None:
    """The production ``python -m`` server path must use provider failover."""
    from contextual_orchestrator import __main__ as cli
    from contextual_orchestrator.passthrough_failover import (
        TaskOrchestrator as FailoverTaskOrchestrator,
    )

    assert cli.TaskOrchestrator is FailoverTaskOrchestrator
