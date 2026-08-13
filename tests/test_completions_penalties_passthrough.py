"""Completions presence/frequency penalties applied on route path."""

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

_TEST_AUTH_TOKEN = "cmpl_penalties_pass_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/completions",
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


def test_http_penalties_applied_then_restored() -> None:
    orch = build()
    seen: list[tuple[float | None, float | None]] = []
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
    prev_p = orch.client.default_presence_penalty
    prev_f = orch.client.default_frequency_penalty
    server = build_server(orch, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "penalize",
                "presence_penalty": 1.5,
                "frequency_penalty": -0.5,
            },
        )
        assert status == 200, body
        assert seen, "chat not invoked"
        assert seen[0][0] == 1.5, seen
        assert seen[0][1] == -0.5, seen
        assert orch.client.default_presence_penalty == prev_p
        assert orch.client.default_frequency_penalty == prev_f
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_presence_out_of_range() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "x", "presence_penalty": 3},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_presence_penalty"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_frequency_out_of_range() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "x", "frequency_penalty": -3},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_frequency_penalty"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_penalties_applied_then_restored()
    test_http_rejects_presence_out_of_range()
    test_http_rejects_frequency_out_of_range()
