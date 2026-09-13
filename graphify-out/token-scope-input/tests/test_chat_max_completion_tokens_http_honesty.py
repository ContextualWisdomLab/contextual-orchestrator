"""Chat Completions max_completion_tokens honesty over HTTP (budget precedence)."""

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

_TEST_AUTH_TOKEN = "chat_max_completion_tokens_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
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


def test_http_chat_accepts_max_completion_tokens() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "budget 64"}],
                "max_completion_tokens": 64,
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_max_completion_tokens_zero() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "zero budget"}],
                "max_completion_tokens": 0,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_max_completion_tokens" in blob
        assert "positive" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_max_completion_tokens_bool() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bool budget"}],
                "max_completion_tokens": True,
            },
        )
        assert status == 400, body
        assert "invalid_max_completion_tokens" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_max_completion_tokens_too_large() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "huge budget"}],
                "max_completion_tokens": 1_048_577,
            },
        )
        assert status == 400, body
        assert "invalid_max_completion_tokens" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_prefers_max_completion_tokens_when_both_set() -> None:
    """When both budgets are present, request must still succeed (max_completion wins)."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "both budgets"}],
                "max_tokens": 8,
                "max_completion_tokens": 32,
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_invalid_max_tokens_when_only_legacy() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "legacy zero"}],
                "max_tokens": 0,
            },
        )
        assert status == 400, body
        assert "invalid_max_tokens" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_max_completion_tokens_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "no budget field"}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_max_completion_tokens()
    test_http_chat_rejects_max_completion_tokens_zero()
    test_http_chat_rejects_max_completion_tokens_bool()
    test_http_chat_rejects_max_completion_tokens_too_large()
    test_http_chat_prefers_max_completion_tokens_when_both_set()
    test_http_chat_rejects_invalid_max_tokens_when_only_legacy()
    test_http_chat_accepts_max_completion_tokens_omitted()
    print("ok")
