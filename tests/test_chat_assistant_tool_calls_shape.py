"""Chat messages: assistant tool_calls array must match OpenAI function shape."""

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

_TEST_AUTH_TOKEN = "chat_assistant_tool_calls_token"  # noqa: S105

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_item",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


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
            raw = response.read().decode("utf-8")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, {"raw": raw}
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_chat_rejects_tool_calls_on_user_role() -> None:
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
                    {
                        "role": "user",
                        "content": "hi",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup_item", "arguments": "{}"},
                            }
                        ],
                    }
                ],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_message"
        assert "assistant" in body["error"]["message"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_calls_missing_id() -> None:
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
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {"name": "lookup_item", "arguments": "{}"},
                            }
                        ],
                    },
                ],
                "tools": _TOOLS,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_message"
        assert "id" in body["error"]["message"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_calls_non_string_arguments() -> None:
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
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup_item", "arguments": {"x": 1}},
                            }
                        ],
                    },
                ],
                "tools": _TOOLS,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_message"
        assert "arguments" in body["error"]["message"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_valid_assistant_tool_calls_shape() -> None:
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
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_lookup_1",
                                "type": "function",
                                "function": {
                                    "name": "lookup_item",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call_lookup_1",
                        "content": "ok",
                    },
                ],
                "tools": _TOOLS,
            },
        )
        if status == 400:
            assert body.get("error", {}).get("code") != "invalid_message", body
        else:
            assert status in (200, 502, 503), body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_tool_calls_on_user_role()
    test_http_chat_rejects_tool_calls_missing_id()
    test_http_chat_rejects_tool_calls_non_string_arguments()
    test_http_chat_accepts_valid_assistant_tool_calls_shape()
