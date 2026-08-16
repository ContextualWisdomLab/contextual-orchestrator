"""Streaming route must apply the request temperature, not a hardcoded 0.2.

The non-stream path writes ``ModelClient.default_temperature`` from the
request, then ``chat()`` uses that default. ``stream_route`` calls
``stream_chat`` without a temperature argument, and ``stream_chat`` still
defaults to ``0.2``. A buyer who streams an invoice summary at
``temperature=0.8`` therefore gets a different sampling policy than the
same body without ``stream``.

OpenAI. (2024). *Create chat completion*. OpenAI API reference.
https://platform.openai.com/docs/api-reference/chat/create
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "stream_chat_request_sampling_http_honesty_token"  # noqa: S105


def test_stream_chat_uses_request_scoped_default_temperature() -> None:
    """Omitted temperature must follow default_temperature, not a hardcoded 0.2."""
    client = ModelClient()
    client.default_temperature = 0.8
    agent = ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))
    list(client.stream_chat(agent, [{"role": "user", "content": "summarize invoice 4419"}]))
    assert getattr(client._local, "last_temperature", None) == 0.8


def test_http_route_stream_applies_request_temperature() -> None:
    """A streamed invoice summary at 0.8 must not silently fall back to 0.2."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )
    seen: dict[str, float | None] = {}
    original = orchestrator.client.stream_chat

    def _capture(agent, messages, temperature=None):
        seen["default_at_call"] = orchestrator.client.default_temperature
        yield from original(agent, messages, temperature)
        seen["last_temperature"] = getattr(orchestrator.client._local, "last_temperature", None)

    orchestrator.client.stream_chat = _capture  # type: ignore[method-assign]
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "summarize invoice 4419"}],
                "mode": "route",
                "stream": True,
                "temperature": 0.8,
            }
        ).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            assert response.headers.get("content-type", "").startswith("text/event-stream")
            body = response.read().decode("utf-8")
        assert "data: [DONE]" in body
        assert seen.get("default_at_call") == 0.8
        assert seen.get("last_temperature") == 0.8
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_stream_chat_uses_request_scoped_default_temperature()
    test_http_route_stream_applies_request_temperature()
    print("ok")
