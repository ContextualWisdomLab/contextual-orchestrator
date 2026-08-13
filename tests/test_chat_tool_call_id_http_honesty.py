"""Chat Completions tool message tool_call_id honesty over HTTP."""

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

_TEST_AUTH_TOKEN = "chat_tool_call_id_http_honesty_token"  # noqa: S105


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


def test_http_chat_accepts_tool_message_with_tool_call_id() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "run tool"},
                    {
                        "role": "tool",
                        "content": "result payload",
                        "tool_call_id": "call_abc123",
                    },
                ],
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_message_missing_tool_call_id() -> None:
    """Buyers must not bind tool results without a tool_call_id."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "run tool"},
                    {"role": "tool", "content": "orphan result"},
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "tool_call_id" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_message_blank_tool_call_id() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "run tool"},
                    {"role": "tool", "content": "blank id", "tool_call_id": "   "},
                ],
            },
        )
        assert status == 400, body
        assert "tool_call_id" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_call_id_too_long() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "run tool"},
                    {
                        "role": "tool",
                        "content": "long id",
                        "tool_call_id": "c" * 129,
                    },
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "tool_call_id" in blob
        assert "128" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_call_id_non_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "run tool"},
                    {"role": "tool", "content": "num id", "tool_call_id": 42},
                ],
            },
        )
        assert status == 400, body
        assert "tool_call_id" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_tool_message_with_tool_call_id()
    test_http_chat_rejects_tool_message_missing_tool_call_id()
    test_http_chat_rejects_tool_message_blank_tool_call_id()
    test_http_chat_rejects_tool_call_id_too_long()
    test_http_chat_rejects_tool_call_id_non_string()
    print("ok")
