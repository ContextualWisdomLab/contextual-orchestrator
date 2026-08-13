"""Completions stop: type-checked then fail-closed (not applied)."""

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

_TEST_AUTH_TOKEN = "cmpl_stop_reject_token"  # noqa: S105


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


def test_http_completions_omits_stop_ok() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(port, {"model": "mock-generalist", "prompt": "Hello"})
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_stop_string() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "Hello", "stop": "\n"},
        )
        assert status == 400, body
        assert "invalid_stop" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_stop_array() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "Hello", "stop": ["END", "STOP"]},
        )
        assert status == 400, body
        assert "invalid_stop" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_stop_too_many() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "Hello",
                "stop": ["a", "b", "c", "d", "e"],
            },
        )
        assert status == 400, body
        assert "invalid_stop" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_omits_stop_ok()
    test_http_completions_rejects_stop_string()
    test_http_completions_rejects_stop_array()
    test_http_completions_rejects_stop_too_many()
    print("ok")
