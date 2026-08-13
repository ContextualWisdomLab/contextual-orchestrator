"""Responses API model field required honesty over HTTP."""

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

_TEST_AUTH_TOKEN = "responses_model_required_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_responses_rejects_missing_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"input": "hello"})
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_model" in blob
        assert "required" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_empty_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "  ", "input": "hello"})
        assert status == 400, body
        assert "invalid_model" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_non_string_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": 12, "input": "hello"})
        assert status == 400, body
        assert "invalid_model" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_overlong_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "m" * 257, "input": "hello"})
        assert status == 400, body
        assert "invalid_model" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_pool_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "mock-planner", "input": "hello"})
        assert status == 200, body
        # OpenAI Responses shape or chat-compatible framing
        assert "output" in body or "choices" in body or body.get("object") in {
            "response",
            "chat.completion",
        } or "id" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_rejects_missing_model()
    test_http_responses_rejects_empty_model()
    test_http_responses_rejects_non_string_model()
    test_http_responses_rejects_overlong_model()
    test_http_responses_accepts_pool_model()
    print("ok")
