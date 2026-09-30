"""Pin provider 429 quota evidence across each chat path."""

from __future__ import annotations

import http.client
import json
import urllib.error
from dataclasses import replace

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelClient

_MESSAGES = [{"role": "user", "content": "summarize the incident"}]


class _Response:
    """A provider 200 response for chat, passthrough, or streaming."""

    def __init__(self, stream: bool) -> None:
        if stream:
            chunk = {
                "model": "second-model",
                "choices": [{"index": 0, "delta": {"content": "ok"}}],
            }
            self._lines = [f"data: {json.dumps(chunk)}\n".encode(), b"data: [DONE]\n"]
        else:
            body = {
                "id": "chatcmpl_ok",
                "object": "chat.completion",
                "created": 0,
                "model": "second-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            }
            self._lines = [json.dumps(body).encode()]
        self.status = 200
        self.headers: dict[str, str] = {}

    def __iter__(self):
        return iter(self._lines)

    def read(self, amount: int | None = None) -> bytes:
        del amount
        body, self._lines = b"".join(self._lines), []
        return body

    def getheader(self, name: str, default: str | None = None) -> str | None:
        del name
        return default

    def close(self) -> None:
        self._lines = []

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        del exc_info
        self.close()
        return False


def _provider_error(status: int) -> urllib.error.HTTPError:
    headers = http.client.HTTPMessage()
    if status == 429:
        headers["Retry-After"] = "7"
    return urllib.error.HTTPError(
        "https://provider.invalid/v1/chat/completions",
        status,
        "provider error",
        headers,
        None,
    )


@pytest.fixture
def pool_for(monkeypatch: pytest.MonkeyPatch):
    """Return a two-member pool whose first provider yields one HTTP error."""
    set_backend(InMemoryCredentialBackend())
    register_credential("SYNTHETIC_PROVIDER_KEY", "synthetic")
    raised: list[urllib.error.HTTPError] = []

    def build(status: int) -> TaskOrchestrator:
        def open_provider(self, request, destination=None, *, timeout=None):
            del self, destination, timeout
            payload = json.loads(request.data.decode())
            if payload["model"] == "first-model":
                raised.append(_provider_error(status))
                raise raised[-1]
            return _Response(stream=bool(payload.get("stream")))

        monkeypatch.setattr(ModelClient, "_validate_provider", lambda self, agent: None)
        monkeypatch.setattr(ModelClient, "_open_provider", open_provider)
        orchestrator = TaskOrchestrator(
            [
                ModelAgent(
                    "first_agent",
                    "first-model",
                    base_url="https://provider.invalid/v1",
                    api_key_env="SYNTHETIC_PROVIDER_KEY",
                    tags=("reasoning", "writing"),
                    priority=10,
                ),
                ModelAgent(
                    "second_agent",
                    "second-model",
                    base_url="https://provider.invalid/v2",
                    api_key_env="SYNTHETIC_PROVIDER_KEY",
                    tags=("reasoning", "writing"),
                    priority=1,
                ),
            ],
            client=ModelClient(max_retries=0),
            tool_retry_attempts=0,
            tool_retry_backoff_seconds=0.0,
            rate_limit_wait_seconds=0.0,
        )
        orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
        orchestrator._triage_fn = lambda text: False
        return orchestrator

    try:
        yield build
    finally:
        for error in raised:
            error.close()
        set_backend(None)


def _serve(orchestrator: TaskOrchestrator, path: str) -> str:
    if path == "route":
        result = orchestrator.route_once(list(_MESSAGES), model_name=TaskOrchestrator.AUTO_MODEL)
        return result["answer"]
    if path == "stream":
        return "".join(
            orchestrator.stream_route(list(_MESSAGES), model_name=TaskOrchestrator.AUTO_MODEL)
        )
    response = orchestrator.proxy_completion(
        {"model": TaskOrchestrator.AUTO_MODEL, "messages": list(_MESSAGES)}
    )
    return response["choices"][0]["message"]["content"]


@pytest.mark.parametrize("path", ["route", "stream", "passthrough"])
def test_provider_429_records_quota_but_not_breaker_health(pool_for, path: str) -> None:
    """A quota response cannot become member-health evidence."""
    orchestrator = pool_for(429)
    assert _serve(orchestrator, path) == "ok"
    assert orchestrator._rate_limit_remaining("first_agent") is not None, path
    assert "first_agent" not in orchestrator._circuit, (path, orchestrator._circuit)


@pytest.mark.parametrize("path", ["route", "stream", "passthrough"])
def test_provider_503_still_counts_as_one_breaker_failure(pool_for, path: str) -> None:
    """A provider availability failure remains breaker evidence."""
    orchestrator = pool_for(503)
    assert _serve(orchestrator, path) == "ok"
    assert orchestrator._circuit["first_agent"]["failures"] == 1.0, path
