"""Chat message prefix honesty: null/false omit; true fail-closed."""

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

_TEST_AUTH_TOKEN = "message_prefix_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_prefix_null_and_false() -> None:
    server, thread, port = _server()
    try:
        for prefix in (None, False):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [
                        {"role": "assistant", "content": "partial", "prefix": prefix},
                        {"role": "user", "content": "continue"},
                    ],
                },
            )
            assert status == 200, (prefix, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_prefix_true() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "assistant", "content": "partial", "prefix": True},
                    {"role": "user", "content": "continue"},
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_prefix" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_prefix_non_boolean() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "assistant", "content": "partial", "prefix": "yes"},
                    {"role": "user", "content": "continue"},
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_prefix" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_prefix_true_with_tools() -> None:
    """Tools passthrough must not skip message-prefix fail-closed checks."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "assistant", "content": "partial", "prefix": True},
                    {"role": "user", "content": "continue with a tool"},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {"name": "lookup_balance", "parameters": {"type": "object"}},
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_prefix" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_prefix_null_and_false()
    test_http_chat_rejects_prefix_true()
    test_http_chat_rejects_prefix_non_boolean()
    test_http_chat_rejects_prefix_true_with_tools()
    print("ok")
