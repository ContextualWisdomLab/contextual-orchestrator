"""Completions max_tokens is applied to the provider client for the request."""

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

_TEST_AUTH_TOKEN = "cmpl_max_tokens_pass_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
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


def test_http_max_tokens_applies_and_restores() -> None:
    orch = build()
    default_cap = orch.client.max_output_tokens
    server = build_server(orch, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "hello", "max_tokens": 64},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        # Restored after request so later work uses the server default again.
        assert orch.client.max_output_tokens == default_cap
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_non_positive_max_tokens() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "hello", "max_tokens": 0},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_max_tokens"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_without_max_tokens_ok() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(port, {"model": "mock-planner", "prompt": "hello"})
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_max_tokens_applies_and_restores()
    test_http_rejects_non_positive_max_tokens()
    test_http_without_max_tokens_ok()


def test_http_rejects_bool_max_tokens() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "hello", "max_tokens": True},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_max_tokens"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_oversized_max_tokens() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "hello", "max_tokens": 2_000_000},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_max_tokens"
    finally:
        server.shutdown()
        thread.join(timeout=5)
