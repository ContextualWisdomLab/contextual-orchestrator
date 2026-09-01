"""Regression contracts for DeepSeek gateway recovery and reasoning deadlines."""

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
        "https://integrate.api.nvidia.com/v1/chat/completions",
        status,
        "provider failure",
        {},
        io.BytesIO(b"{}"),
    )


def _deepseek_agent() -> ModelAgent:
    """Return the route shape involved in the DiagramWeave incident."""
    return ModelAgent(
        "nvidia_nim_deepseek_v4_flash",
        "deepseek-ai/deepseek-v4-flash-0731",
        base_url="https://integrate.api.nvidia.com/v1",
        provider_name="nvidia_nim",
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


def test_proxy_send_recovers_after_one_deepseek_502() -> None:
    """One transient gateway 502 must not permanently discard the route."""
    response = {
        "choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]
    }
    client = _GatewayClient([_http_error(502), response], max_retries=1)

    result = client.proxy_send(
        _deepseek_agent(),
        "chat/completions",
        {"model": "deepseek-ai/deepseek-v4-flash-0731", "messages": []},
    )

    assert result == response
    assert client.attempts == 2


def test_proxy_send_does_not_retry_permanent_auth_failure() -> None:
    """A 401 remains terminal even when the client has a retry budget."""
    client = _GatewayClient([_http_error(401)], max_retries=3)

    with pytest.raises(ProviderUpstreamError) as excinfo:
        client.proxy_send(
            _deepseek_agent(),
            "chat/completions",
            {"model": "deepseek-ai/deepseek-v4-flash-0731", "messages": []},
        )

    assert excinfo.value.provider_status == 401
    assert client.attempts == 1


def test_model_client_has_no_default_reasoning_deadline() -> None:
    """Slow reasoning is bounded by caller cancellation, not a hidden 90-second cap."""
    client = ModelClient()

    assert client.timeout is None
    assert client.connect_timeout is None
