"""Chat messages: tool role requires tool_call_id; other roles reject it."""

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

_TEST_AUTH_TOKEN = "chat_tool_call_id_token"  # noqa: S105


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


def test_http_chat_rejects_tool_message_without_tool_call_id() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "tool", "content": "result"},
                ],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_tool_call_id"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_call_id_on_user_message() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [
                    {"role": "user", "content": "hi", "tool_call_id": "call_1"},
                ],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_tool_call_id"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_oversized_tool_call_id() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {
                        "role": "tool",
                        "content": "result",
                        "tool_call_id": "c" * 129,
                    },
                ],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_tool_call_id"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_message_with_tool_call_id() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {
                        "role": "tool",
                        "content": "lookup ok",
                        "tool_call_id": "call_abc123",
                    },
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_tool_message_without_tool_call_id()
    test_http_chat_rejects_tool_call_id_on_user_message()
    test_http_chat_rejects_oversized_tool_call_id()
    test_http_chat_accepts_tool_message_with_tool_call_id()
