"""Completions model: required non-empty string; missing/empty/too-long fail-closed."""

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

_TEST_AUTH_TOKEN = "cmpl_model_required_token"  # noqa: S105


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


def test_http_completions_accepts_model_string() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "Hello"},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_missing_model() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(port, {"prompt": "Hello"})
        assert status == 400, body
        assert "invalid_model" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_empty_model() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "  ", "prompt": "Hello"},
        )
        assert status == 400, body
        assert "invalid_model" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_model_too_long() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "m" * 257, "prompt": "Hello"},
        )
        assert status == 400, body
        assert "invalid_model" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_accepts_model_string()
    test_http_completions_rejects_missing_model()
    test_http_completions_rejects_empty_model()
    test_http_completions_rejects_model_too_long()
    print("ok")
