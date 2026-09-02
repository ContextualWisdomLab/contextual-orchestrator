"""Regression contracts for provider retry and inference deadlines."""

from __future__ import annotations

import io
import urllib.error

import pytest

from contextual_orchestrator import ModelAgent
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.provider_errors import ProviderUpstreamError


def _http_error(status: int) -> urllib.error.HTTPError:
    """Build one deterministic OpenAI-compatible provider failure."""
    return urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions",
        status,
        "provider failure",
        {},
        io.BytesIO(b"{}"),
    )


def _agent(*, reasoning_effort_supported: bool | None) -> ModelAgent:
    """Return a provider-neutral chat route with explicit capability evidence."""
    return ModelAgent(
        "provider_route",
        "arbitrary-chat-model",
        base_url="https://provider.example/v1",
        provider_name="provider",
        reasoning_effort_supported=reasoning_effort_supported,
    )


class _GatewayClient(ModelClient):
    """Expose deterministic raw-provider outcomes through the public proxy seam."""

    def __init__(self, outcomes: list[object], *, max_retries: int) -> None:
        """Store provider outcomes and disable real retry sleeping."""
        super().__init__(max_retries=max_retries, retry_backoff=0.0)
        self._outcomes = iter(outcomes)
        self.attempts = 0

    def _validate_provider(self, agent: ModelAgent):  # type: ignore[override]
        """Bypass DNS validation because this test never opens a socket."""
        del agent
        return None

    def _send_raw(  # type: ignore[override]
        self,
        agent: ModelAgent,
        endpoint: str,
        payload: dict[str, object],
        destination=None,
    ) -> dict[str, object]:
        """Return or raise the next transport outcome."""
        del agent, endpoint, payload, destination
        self.attempts += 1
        outcome = next(self._outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, dict)
        return outcome


@pytest.mark.parametrize("reasoning_effort_supported", [None, False, True])
def test_proxy_send_recovers_transient_502_independent_of_reasoning_capability(
    reasoning_effort_supported: bool | None,
) -> None:
    """Transport retry depends on failure taxonomy, never a model family or capability flag."""
    response = {
        "choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]
    }
    client = _GatewayClient([_http_error(502), response], max_retries=1)
    agent = _agent(reasoning_effort_supported=reasoning_effort_supported)

    result = client.proxy_send(
        agent,
        "chat/completions",
        {"model": agent.model, "messages": []},
    )

    assert result == response
    assert client.attempts == 2


def test_proxy_send_does_not_retry_permanent_auth_failure() -> None:
    """A 401 remains terminal even when the client has a retry budget."""
    client = _GatewayClient([_http_error(401)], max_retries=3)
    agent = _agent(reasoning_effort_supported=True)

    with pytest.raises(ProviderUpstreamError) as excinfo:
        client.proxy_send(
            agent,
            "chat/completions",
            {"model": agent.model, "messages": []},
        )

    assert excinfo.value.provider_status == 401
    assert client.attempts == 1


def test_model_client_has_no_default_inference_deadline() -> None:
    """Every model may run until explicit caller or workflow cancellation."""
    client = ModelClient()

    assert client.timeout is None
