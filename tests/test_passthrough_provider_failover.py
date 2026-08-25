"""Cross-provider failover contracts for raw OpenAI passthrough requests."""

from __future__ import annotations

import urllib.error
from copy import deepcopy
from typing import Any

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator


class SequencedProxyClient:
    """Return one configured outcome per provider while recording attempts."""

    def __init__(self, outcomes: dict[str, dict[str, Any] | BaseException]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def proxy_send_once(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Perform one deterministic passthrough attempt."""
        del endpoint
        self.calls.append((agent.id, deepcopy(payload)))
        outcome = self.outcomes[agent.id]
        if isinstance(outcome, BaseException):
            raise outcome
        return deepcopy(outcome)

    proxy_send = proxy_send_once


def _http_error(status: int) -> urllib.error.HTTPError:
    """Build a provider-shaped HTTP failure."""
    return urllib.error.HTTPError("https://provider.example/v1", status, "failed", None, None)


def _build(client: SequencedProxyClient) -> TaskOrchestrator:
    """Build a two-provider pool with deterministic priority."""
    return TaskOrchestrator(
        [
            ModelAgent("primary_agent", "primary-model", priority=10),
            ModelAgent("fallback_agent", "fallback-model", priority=1),
        ],
        client=client,
    )


@pytest.mark.parametrize("status", [404, 410, 429, 503])
def test_virtual_passthrough_advances_once_and_preserves_request(status: int) -> None:
    """Adaptive requests advance once on transient or stale-model failures."""
    client = SequencedProxyClient(
        {
            "primary_agent": _http_error(status),
            "fallback_agent": {"model": "fallback-model", "choices": []},
        }
    )
    body = {
        "model": "contextual-orchestrator",
        "messages": [{"role": "user", "content": "review code"}],
        "tools": [{"type": "function", "function": {"name": "inspect"}}],
        "response_format": {"type": "json_object"},
        "stream": True,
    }

    result = _build(client).proxy_completion(body)

    assert result["model"] == "fallback-model"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent", "fallback_agent"]
    assert client.calls[1][1]["tools"] == body["tools"]
    assert client.calls[1][1]["response_format"] == body["response_format"]
    assert client.calls[1][1]["stream"] is False


@pytest.mark.parametrize("status", [404, 429])
def test_explicit_model_never_fails_over(status: int) -> None:
    """A concrete model selection remains sticky even when its provider fails."""
    failure = _http_error(status)
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )

    with pytest.raises(urllib.error.HTTPError) as caught:
        _build(client).proxy_completion(
            {"model": "primary-model", "messages": [{"role": "user", "content": "x"}]}
        )

    assert caught.value is failure
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_non_transient_error_is_not_replayed() -> None:
    """Caller errors fail closed instead of duplicating a request across providers."""
    failure = _http_error(400)
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )

    with pytest.raises(urllib.error.HTTPError) as caught:
        _build(client).proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert caught.value is failure
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_wrapped_transient_error_can_fail_over() -> None:
    """Provider SDK wrappers retain their causal failover signal."""
    try:
        raise RuntimeError("provider wrapper") from _http_error(429)
    except RuntimeError as wrapped:
        failure = wrapped
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )

    assert _build(client).proxy_completion(
        {"messages": [{"role": "user", "content": "x"}]}
    )["model"] == "fallback-model"


def test_suppressed_transient_context_does_not_authorize_failover() -> None:
    """A deliberately hidden exception context cannot become a routing signal."""
    try:
        raise _http_error(429)
    except urllib.error.HTTPError:
        try:
            raise RuntimeError("terminal wrapper") from None
        except RuntimeError as wrapped:
            failure = wrapped
    client = SequencedProxyClient(
        {
            "primary_agent": failure,
            "fallback_agent": {"model": "fallback-model"},
        }
    )

    with pytest.raises(RuntimeError, match="terminal wrapper") as caught:
        _build(client).proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert caught.value is failure
    assert [agent_id for agent_id, _ in client.calls] == ["primary_agent"]


def test_all_candidates_chain_the_last_failure() -> None:
    """Exhaustion reports one stable gateway error with the final provider cause."""
    final = _http_error(503)
    orchestrator = _build(
        SequencedProxyClient({"primary_agent": _http_error(429), "fallback_agent": final})
    )

    with pytest.raises(RuntimeError, match="all 2 candidate agents failed") as caught:
        orchestrator.proxy_completion({"messages": [{"role": "user", "content": "x"}]})

    assert caught.value.__cause__ is final
