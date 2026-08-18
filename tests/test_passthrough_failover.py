"""Regression tests for provider failover on full-shape OpenAI passthrough."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator


class SequencedProxyClient:
    """Return configured raw responses or raise configured errors by agent ID."""

    def __init__(self, outcomes: dict[str, dict[str, Any] | BaseException]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def proxy_send(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Record one call and return or raise the configured outcome."""
        self.calls.append((agent.id, endpoint, deepcopy(payload)))
        outcome = self.outcomes[agent.id]
        if isinstance(outcome, BaseException):
            raise outcome
        return deepcopy(outcome)


def _orchestrator(client: SequencedProxyClient) -> TaskOrchestrator:
    """Build a deterministic two-provider passthrough pool."""
    return TaskOrchestrator(
        agents=[
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


def test_proxy_completion_fails_over_after_primary_rate_limit_and_preserves_tools() -> None:
    """A rate-limited tool-call provider must hand the unchanged request to fallback."""
    client = SequencedProxyClient(
        {
            "primary_agent": RuntimeError("429 rate limit"),
            "fallback_agent": {
                "object": "chat.completion",
                "model": "fallback-model",
                "choices": [],
            },
        }
    )
    orchestrator = _orchestrator(client)
    tools = [{"type": "function", "function": {"name": "inspect", "parameters": {}}}]
    body = {
        "messages": [{"role": "user", "content": "review this security-sensitive code"}],
        "tools": tools,
        "mode": "auto",
    }
    original = deepcopy(body)

    result = orchestrator.proxy_completion(body)

    assert result["model"] == "fallback-model"
    assert [call[0] for call in client.calls] == ["primary_agent", "fallback_agent"]
    assert client.calls[0][2]["model"] == "primary-model"
    assert client.calls[1][2]["model"] == "fallback-model"
    assert client.calls[1][2]["tools"] == tools
    assert "mode" not in client.calls[1][2]
    assert body == original


def test_proxy_completion_reports_all_candidate_failures() -> None:
    """The gateway must fail closed after every eligible passthrough provider fails."""
    first = RuntimeError("primary unavailable")
    final = RuntimeError("fallback unavailable")
    client = SequencedProxyClient(
        {"primary_agent": first, "fallback_agent": final}
    )
    orchestrator = _orchestrator(client)

    with pytest.raises(RuntimeError, match="all 2 candidate agents failed") as caught:
        orchestrator.proxy_completion(
            {
                "messages": [{"role": "user", "content": "review code"}],
                "tools": [],
            }
        )

    assert caught.value.__cause__ is final
    assert [call[0] for call in client.calls] == ["primary_agent", "fallback_agent"]
