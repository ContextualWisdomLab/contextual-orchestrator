"""Streaming route must apply request top_p and penalties, not drop them.

``18e6263`` made ``stream_chat`` honor ``default_temperature``. The HTTP
handler also writes ``default_top_p``, ``default_presence_penalty``, and
``default_frequency_penalty`` from the request, and ``chat()`` copies those
into the provider payload. ``stream_chat`` still records only temperature.
A buyer who streams an invoice summary at ``top_p=0.1`` therefore pays for
a completion that ignored nucleus sampling.

OpenAI. (2024). *Create chat completion*. OpenAI API reference.
https://platform.openai.com/docs/api-reference/chat/create

Holtzman, A., Buys, J., Du, L., Forbes, M., & Choi, Y. (2020). The curious
case of neural text degeneration. *International Conference on Learning
Representations*. https://arxiv.org/abs/1904.09751
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

_TEST_AUTH_TOKEN = "stream_chat_request_nucleus_penalties_http_honesty_token"  # noqa: S105


def test_stream_chat_uses_request_scoped_nucleus_and_penalties() -> None:
    """Omitted stream knobs must follow the request-scoped ModelClient defaults."""
    client = ModelClient()
    client.default_top_p = 0.1
    client.default_presence_penalty = 0.5
    client.default_frequency_penalty = -0.25
    agent = ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))
    list(client.stream_chat(agent, [{"role": "user", "content": "summarize invoice 4419"}]))
    assert getattr(client._local, "last_top_p", None) == 0.1
    assert getattr(client._local, "last_presence_penalty", None) == 0.5
    assert getattr(client._local, "last_frequency_penalty", None) == -0.25


def test_http_route_stream_applies_request_nucleus_and_penalties() -> None:
    """A streamed invoice summary at top_p=0.1 must not silently drop nucleus."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )
    seen: dict[str, float | None] = {}
    original = orchestrator.client.stream_chat

    def _capture(agent, messages, temperature=None):
        seen["default_top_p_at_call"] = orchestrator.client.default_top_p
        seen["default_presence_at_call"] = orchestrator.client.default_presence_penalty
        seen["default_frequency_at_call"] = orchestrator.client.default_frequency_penalty
        yield from original(agent, messages, temperature)
        seen["last_top_p"] = getattr(orchestrator.client._local, "last_top_p", None)
        seen["last_presence_penalty"] = getattr(
            orchestrator.client._local, "last_presence_penalty", None
        )
        seen["last_frequency_penalty"] = getattr(
            orchestrator.client._local, "last_frequency_penalty", None
        )

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
                "top_p": 0.1,
                "presence_penalty": 0.5,
                "frequency_penalty": -0.25,
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
        assert seen.get("default_top_p_at_call") == 0.1
        assert seen.get("default_presence_at_call") == 0.5
        assert seen.get("default_frequency_at_call") == -0.25
        assert seen.get("last_top_p") == 0.1
        assert seen.get("last_presence_penalty") == 0.5
        assert seen.get("last_frequency_penalty") == -0.25
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_stream_chat_uses_request_scoped_nucleus_and_penalties()
    test_http_route_stream_applies_request_nucleus_and_penalties()
    print("ok")
