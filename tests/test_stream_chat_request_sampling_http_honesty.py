"""Streaming route must apply the request sampling knobs, not a subset.

The non-stream path writes ``ModelClient.default_temperature`` /
``default_top_p`` / ``default_presence_penalty`` / ``default_frequency_penalty``
from the request, then ``chat()`` uses those defaults. ``stream_route``
calls ``stream_chat`` without those arguments. Temperature is already
request-scoped; ``top_p`` / penalties were still omitted from the stream
payload. A buyer who streams an invoice summary at ``top_p=0.1`` therefore
gets a different nucleus/penalty policy than the same body without
``stream``.

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


def test_stream_chat_uses_request_scoped_default_sampling_knobs() -> None:
    """Omitted stream knobs must follow the same defaults ``chat()`` already applies."""
    client = ModelClient()
    client.default_temperature = 0.8
    client.default_top_p = 0.1
    client.default_presence_penalty = 0.2
    client.default_frequency_penalty = 0.3
    agent = ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))
    list(client.stream_chat(agent, [{"role": "user", "content": "summarize invoice 4419"}]))
    assert getattr(client._local, "last_temperature", None) == 0.8
    assert getattr(client._local, "last_top_p", None) == 0.1
    assert getattr(client._local, "last_presence_penalty", None) == 0.2
    assert getattr(client._local, "last_frequency_penalty", None) == 0.3


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


def test_http_route_stream_applies_request_nucleus_and_penalties() -> None:
    """A streamed invoice summary at top_p=0.1 must not drop nucleus/penalty knobs."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )
    seen: dict[str, float | None] = {}
    original = orchestrator.client.stream_chat

    def _capture(agent, messages, temperature=None):
        seen["default_top_p"] = orchestrator.client.default_top_p
        seen["default_presence"] = orchestrator.client.default_presence_penalty
        seen["default_frequency"] = orchestrator.client.default_frequency_penalty
        yield from original(agent, messages, temperature)
        seen["last_top_p"] = getattr(orchestrator.client._local, "last_top_p", None)
        seen["last_presence"] = getattr(orchestrator.client._local, "last_presence_penalty", None)
        seen["last_frequency"] = getattr(orchestrator.client._local, "last_frequency_penalty", None)

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
                "top_p": 0.1,
                "presence_penalty": 0.2,
                "frequency_penalty": 0.3,
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
        assert seen.get("default_top_p") == 0.1
        assert seen.get("default_presence") == 0.2
        assert seen.get("default_frequency") == 0.3
        assert seen.get("last_top_p") == 0.1
        assert seen.get("last_presence") == 0.2
        assert seen.get("last_frequency") == 0.3
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_stream_chat_uses_request_scoped_default_temperature()
    test_stream_chat_uses_request_scoped_default_sampling_knobs()
    test_http_route_stream_applies_request_temperature()
    test_http_route_stream_applies_request_nucleus_and_penalties()
    print("ok")
