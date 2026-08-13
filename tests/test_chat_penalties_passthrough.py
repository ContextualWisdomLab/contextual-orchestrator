"""Chat Completions presence/frequency penalties applied on route path."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "chat_penalties_pass_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_chat_penalties_applied() -> None:
    orch = build()
    seen = []
    original = orch.client.chat

    def capture(agent, messages, temperature=None, top_p=None):  # type: ignore[no-untyped-def]
        result = original(agent, messages, temperature=temperature, top_p=top_p)
        seen.append(
            (
                getattr(orch.client._local, "last_presence_penalty", None),
                getattr(orch.client._local, "last_frequency_penalty", None),
            )
        )
        return result

    orch.client.chat = capture  # type: ignore[method-assign]
    prev = (orch.client.default_presence_penalty, orch.client.default_frequency_penalty)
    server = build_server(orch, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "presence_penalty": 1.25,
                "frequency_penalty": -1.0,
            },
        )
        assert status == 200, body
        assert seen and seen[0] == (1.25, -1.0), seen
        assert (orch.client.default_presence_penalty, orch.client.default_frequency_penalty) == prev
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_bad_presence() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "presence_penalty": 9,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_presence_penalty"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_penalties_applied()
    test_http_chat_rejects_bad_presence()
