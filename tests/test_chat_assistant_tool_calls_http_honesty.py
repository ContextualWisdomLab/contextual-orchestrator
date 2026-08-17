"""Chat Completions assistant tool_calls array shape honesty over HTTP."""

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

_TEST_AUTH_TOKEN = "chat_assistant_tool_calls_http_honesty_token"  # noqa: S105


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


def _valid_tool_call(*, call_id: str = "call_1", name: str = "lookup_item") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": "{\"q\":\"x\"}"},
    }


def test_http_chat_accepts_assistant_tool_calls_shape() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "use the tool"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [_valid_tool_call()],
                    },
                    {
                        "role": "tool",
                        "content": "result payload",
                        "tool_call_id": "call_1",
                    },
                    {"role": "user", "content": "thanks"},
                ],
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_calls_on_user_message() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": "nope",
                        "tool_calls": [_valid_tool_call()],
                    },
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "assistant" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_empty_tool_calls_array_as_omit() -> None:
    """Empty tool_calls is omit-equivalent (SDK no-op history slot)."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "", "tool_calls": []},
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_calls_missing_id() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
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
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "id" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_calls_bad_type() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "custom",
                                "function": {"name": "lookup_item", "arguments": "{}"},
                            }
                        ],
                    },
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "function" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_calls_object_arguments_as_json_text() -> None:
    """Parsed object/array arguments serialize to OpenAI JSON-text wire form."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup_item", "arguments": {"q": 1}},
                            }
                        ],
                    },
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_calls_non_json_arguments() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup_item", "arguments": 3},
                            }
                        ],
                    },
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "arguments" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_calls_bad_function_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "bad name!", "arguments": "{}"},
                            }
                        ],
                    },
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "function.name" in blob or "a-zA-Z0-9" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_assistant_tool_calls_shape()
    test_http_chat_rejects_tool_calls_on_user_message()
    test_http_chat_accepts_empty_tool_calls_array_as_omit()
    test_http_chat_rejects_tool_calls_missing_id()
    test_http_chat_rejects_tool_calls_bad_type()
    test_http_chat_accepts_tool_calls_object_arguments_as_json_text()
    test_http_chat_rejects_tool_calls_non_json_arguments()
    test_http_chat_rejects_tool_calls_bad_function_name()
    print("ok")
