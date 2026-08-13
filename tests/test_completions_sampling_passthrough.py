"""Completions temperature/top_p applied to ModelClient for the request path."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    SecurityConfig,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_sampling_pass_token"  # noqa: S105


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


def test_http_temperature_and_top_p_applied_then_restored() -> None:
    orch = build()
    seen: list[tuple[float, float | None]] = []
    original_chat = orch.client.chat

    def capture_chat(agent, messages, temperature=None, top_p=None):  # type: ignore[no-untyped-def]
        # Call real chat so mock path + last_* diagnostics still run.
        result = original_chat(agent, messages, temperature=temperature, top_p=top_p)
        seen.append(
            (
                getattr(orch.client._local, "last_temperature", None),
                getattr(orch.client._local, "last_top_p", None),
            )
        )
        return result

    orch.client.chat = capture_chat  # type: ignore[method-assign]
    default_temp = orch.client.default_temperature
    default_top_p = orch.client.default_top_p
    default_max = orch.client.max_output_tokens

    server = build_server(orch, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "sample me",
                "temperature": 1.7,
                "top_p": 0.4,
                "max_tokens": 32,
            },
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert seen, "chat was not invoked on Completions route path"
        assert seen[0][0] == 1.7, seen
        assert seen[0][1] == 0.4, seen
        # Restored after the request for later work.
        assert orch.client.default_temperature == default_temp
        assert orch.client.default_top_p == default_top_p
        assert orch.client.max_output_tokens == default_max
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_out_of_range_temperature() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "x", "temperature": 3.0},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_temperature"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_zero_top_p() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "x", "top_p": 0},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_top_p"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_temperature_and_top_p_applied_then_restored()
    test_http_rejects_out_of_range_temperature()
    test_http_rejects_zero_top_p()
