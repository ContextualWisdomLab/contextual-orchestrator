"""Chat Completions store honesty over HTTP (OpenAI store persistence knob)."""

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

_TEST_AUTH_TOKEN = "chat_store_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
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


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_rejects_store_true() -> None:
    """Buyers must not believe store=true persisted a completion when it cannot."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "remember this"}],
                "store": True,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_store" in blob
        assert "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_store_false() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "no store please"}],
                "store": False,
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_store_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "default store omit"}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_store_non_boolean() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bad store type"}],
                "store": "yes",
            },
        )
        assert status == 400, body
        assert "invalid_store" in json.dumps(body)
        assert "boolean" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_store_null_as_omit() -> None:
    """Explicit JSON null is an SDK optional default — omit-equivalent no-op."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "null store"}],
                "store": None,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_store_true()
    test_http_chat_accepts_store_false()
    test_http_chat_accepts_store_omitted()
    test_http_chat_rejects_store_non_boolean()
    test_http_chat_accepts_store_null_as_omit()
    print("ok")
