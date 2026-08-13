"""Chat Completions temperature/top_p/max_tokens applied on route path."""

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

_TEST_AUTH_TOKEN = "chat_sampling_pass_token"  # noqa: S105


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


def test_http_chat_sampling_applied_then_restored() -> None:
    orch = build()
    seen: list[tuple[float, float | None, int]] = []
    original = orch.client.chat

    def capture(agent, messages, temperature=None, top_p=None):  # type: ignore[no-untyped-def]
        result = original(agent, messages, temperature=temperature, top_p=top_p)
        seen.append(
            (
                getattr(orch.client._local, "last_temperature", None),
                getattr(orch.client._local, "last_top_p", None),
                orch.client.max_output_tokens,
            )
        )
        return result

    orch.client.chat = capture  # type: ignore[method-assign]
    defaults = (
        orch.client.default_temperature,
        orch.client.default_top_p,
        orch.client.max_output_tokens,
    )
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
                "temperature": 0.9,
                "top_p": 0.5,
                "max_tokens": 48,
            },
        )
        assert status == 200, body
        assert body["object"] == "chat.completion"
        assert seen, "chat not invoked"
        assert seen[0][0] == 0.9, seen
        assert seen[0][1] == 0.5, seen
        assert seen[0][2] == 48, seen
        assert (
            orch.client.default_temperature,
            orch.client.default_top_p,
            orch.client.max_output_tokens,
        ) == defaults
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_bad_temperature() -> None:
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
                "temperature": 5,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_temperature"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_without_sampling_ok() -> None:
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
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_sampling_applied_then_restored()
    test_http_chat_rejects_bad_temperature()
    test_http_chat_without_sampling_ok()
