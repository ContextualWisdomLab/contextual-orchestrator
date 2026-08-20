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


def _http_error(status: int, message: str) -> urllib.error.HTTPError:
    """Return a realistic provider HTTP error for passthrough routing tests."""
    return urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions",
        status,
        message,
        None,
        None,
    )


def _rate_limit() -> urllib.error.HTTPError:
    """Return a realistic transient provider HTTP 429 error."""
    return _http_error(429, "rate limited")


def _wrapped(error: BaseException) -> RuntimeError:
    """Return a provider-style wrapper with the original failure as its cause."""
    try:
        raise RuntimeError("provider wrapper") from error
    except RuntimeError as wrapper:
        return wrapper


def _suppressed_wrapper(error: BaseException) -> RuntimeError:
    """Return a terminal wrapper whose incidental context is explicitly hidden."""
    try:
        raise error
    except BaseException:
        try:
            raise RuntimeError("terminal provider wrapper") from None
        except RuntimeError as wrapper:
            return wrapper


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


@pytest.mark.parametrize("status", [404, 410])
def test_virtual_request_advances_when_discovered_candidate_disappears(
    status: int,
) -> None:
    """A stale discovered candidate must not block another compatible worker."""
    unavailable = _http_error(status, "model unavailable")
    client = SequencedProxyClient(
        {
            "primary_agent": unavailable,
            "fallback_agent": {
                "object": "chat.completion",
                "model": "fallback-model",
                "choices": [],
            },
        }
    )
    orchestrator = _build(client)

    result = orchestrator.proxy_completion(
        {
            "model": "contextual-orchestrator",
            "messages": [{"role": "user", "content": "review code"}],
            "tools": [],
        }
    )

    assert result["model"] == "fallback-model"
    assert [call[0] for call in client.calls] == ["primary_agent", "fallback_agent"]


@pytest.mark.parametrize("provider_error", [_rate_limit(), _http_error(410, "gone")])
def test_virtual_request_unwraps_provider_failure_causes(
    provider_error: BaseException,
) -> None:
    """Provider SDK wrappers must not hide a bounded fallback signal."""
    client = SequencedProxyClient(
        {
            "primary_agent": _wrapped(provider_error),
            "fallback_agent": {
                "object": "chat.completion",
                "model": "fallback-model",
                "choices": [],
            },
        }
    )
    orchestrator = _build(client)

    result = orchestrator.proxy_completion(
        {
            "model": "contextual-orchestrator",
            "messages": [{"role": "user", "content": "review code"}],
            "tools": [],
        }
    )

    assert result["model"] == "fallback-model"
    assert [call[0] for call in client.calls] == ["primary_agent", "fallback_agent"]


def test_suppressed_provider_context_does_not_authorize_failover() -> None:
    """An explicitly suppressed prior 429 must not override a terminal wrapper."""
    terminal = _suppressed_wrapper(_rate_limit())
    client = SequencedProxyClient(
        {
            "primary_agent": terminal,
            "fallback_agent": {
                "object": "chat.completion",
                "model": "fallback-model",
                "choices": [],
            },
        }
    )
    orchestrator = _build(client)

    with pytest.raises(RuntimeError, match="terminal provider wrapper") as caught:
        orchestrator.proxy_completion(
            {
                "model": "contextual-orchestrator",
                "messages": [{"role": "user", "content": "review code"}],
                "tools": [],
            }
        )

    assert caught.value is terminal
    assert terminal.__suppress_context__ is True
    assert [call[0] for call in client.calls] == ["primary_agent"]


@pytest.mark.parametrize("status", [404, 410])
def test_explicit_concrete_model_remains_sticky_when_unavailable(status: int) -> None:
    """An explicit concrete model must never be silently replaced."""
    unavailable = _http_error(status, "model unavailable")
    client = SequencedProxyClient(
        {
            "primary_agent": unavailable,
            "fallback_agent": {
                "object": "chat.completion",
                "model": "fallback-model",
                "choices": [],
            },
        }
    )
    orchestrator = _build(client)

    with pytest.raises(urllib.error.HTTPError) as caught:
        orchestrator.proxy_completion(
            {
                "model": "primary-model",
                "messages": [{"role": "user", "content": "review code"}],
                "tools": [],
            }
        )

    assert caught.value is unavailable
    assert [call[0] for call in client.calls] == ["primary_agent"]


def test_explicit_concrete_model_preserves_rate_limit_error() -> None:
    """A concrete-model 429 must remain the provider's original error."""
    rate_limit = _rate_limit()
    client = SequencedProxyClient(
        {
            "primary_agent": rate_limit,
            "fallback_agent": {
                "object": "chat.completion",
                "model": "fallback-model",
                "choices": [],
            },
        }
    )
    orchestrator = _build(client)

    with pytest.raises(urllib.error.HTTPError) as caught:
        orchestrator.proxy_completion(
            {
                "model": "primary-model",
                "messages": [{"role": "user", "content": "review code"}],
                "tools": [],
            }
        )

    assert caught.value is rate_limit
    assert [call[0] for call in client.calls] == ["primary_agent"]


def test_non_transient_request_error_is_not_replayed_to_another_provider() -> None:
    """A provider 400 is caller/configuration evidence, not a failover signal."""
    bad_request = _http_error(400, "unsupported request")
    client = SequencedProxyClient(
        {
            "primary_agent": bad_request,
            "fallback_agent": {
                "object": "chat.completion",
                "model": "fallback-model",
                "choices": [],
            },
        }
    )
    orchestrator = _build(client)

    with pytest.raises(urllib.error.HTTPError) as caught:
        orchestrator.proxy_completion(
            {
                "messages": [{"role": "user", "content": "invalid request"}],
                "tools": [],
            }
        )

    assert caught.value is bad_request
    assert [call[0] for call in client.calls] == ["primary_agent"]
    assert not orchestrator._circuit_open("primary_agent")


def test_all_transient_candidate_failures_chain_final_provider_error() -> None:
    """Exhausted transient candidates fail closed with the final provider cause."""
    first = _rate_limit()
    final = _http_error(503, "fallback unavailable")
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
