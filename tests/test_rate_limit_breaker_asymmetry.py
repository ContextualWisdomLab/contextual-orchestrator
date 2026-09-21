"""Characterize (not endorse) how the two chat paths charge a provider 429.

One identical provider response -- HTTP 429 with ``Retry-After: 7`` from the
first-ranked agent, success from the second -- is served at the lowest
transport seam (``ModelClient._open_provider``) to the same pool and the same
request through (1) ``route_once`` -> ``_invoke`` and (2) the virtual
passthrough loop in ``proxy_completion``. Both record the quota cooldown; only
``_invoke`` also charges the breaker. The policy analysis lives in
``docs/doctoring/observed-health-quarantine.md`` ("429 study"); this file pins
current behavior so a future change is deliberate.
"""

from __future__ import annotations

import http.client
import json
import sys
import urllib.error
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


class _Response:
    def __init__(self) -> None:
        self._body = json.dumps(
            {
                "id": "chatcmpl_ok",
                "object": "chat.completion",
                "created": 0,
                "model": "second-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            }
        ).encode("utf-8")
        self.status = 200
        self.headers: dict[str, str] = {}

    def read(self, amount: int | None = None) -> bytes:
        body, self._body = self._body, b""
        return body

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return default

    def close(self) -> None:
        self._body = b""

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.close()
        return False


def _rate_limited() -> urllib.error.HTTPError:
    headers = http.client.HTTPMessage()
    headers["Retry-After"] = "7"
    return urllib.error.HTTPError("https://provider.invalid/v1/chat/completions", 429, "Too Many Requests", headers, None)


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch):
    set_backend(InMemoryCredentialBackend())
    register_credential("SYNTHETIC_PROVIDER_KEY", "synthetic")
    raised: list[urllib.error.HTTPError] = []  # the fake provider owns its responses

    def open_provider(self, request, destination=None, *, timeout=None):
        del self, destination, timeout
        if json.loads(request.data.decode("utf-8"))["model"] == "first-model":
            raised.append(_rate_limited())
            raise raised[-1]
        return _Response()

    monkeypatch.setattr(ModelClient, "_validate_provider", lambda self, agent: None)
    monkeypatch.setattr(ModelClient, "_open_provider", open_provider)
    agents = [
        ModelAgent("first_agent", "first-model", base_url="https://provider.invalid/v1",
                   api_key_env="SYNTHETIC_PROVIDER_KEY", tags=("reasoning", "writing"), priority=10),
        ModelAgent("second_agent", "second-model", base_url="https://provider.invalid/v2",
                   api_key_env="SYNTHETIC_PROVIDER_KEY", tags=("reasoning", "writing"), priority=1),
    ]
    orchestrator = TaskOrchestrator(
        agents,
        client=ModelClient(max_retries=0),
        tool_retry_attempts=0,
        tool_retry_backoff_seconds=0.0,
        rate_limit_wait_seconds=0.0,
    )
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    orchestrator._triage_fn = lambda text: False
    try:
        yield orchestrator
    finally:
        for error in raised:
            error.close()
        set_backend(None)


_MESSAGES = [{"role": "user", "content": "summarize the incident"}]


def test_invoke_path_charges_provider_429_to_the_breaker(pool: TaskOrchestrator) -> None:
    result = pool.route_once(list(_MESSAGES), model_name=TaskOrchestrator.AUTO_MODEL)
    assert result["trace"][0]["served_agent_id"] == "second_agent"
    assert pool._rate_limit_remaining("first_agent") is not None  # quota cooldown recorded
    assert pool._circuit["first_agent"]["failures"] == 1.0  # ... and a health failure


def test_passthrough_path_keeps_provider_429_out_of_the_breaker(pool: TaskOrchestrator) -> None:
    response = pool.proxy_completion({"model": TaskOrchestrator.AUTO_MODEL, "messages": list(_MESSAGES)})
    assert response["choices"][0]["message"]["content"] == "ok"
    assert pool._rate_limit_remaining("first_agent") is not None  # quota cooldown recorded
    assert "first_agent" not in pool._circuit  # ... but no health failure
