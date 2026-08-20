"""tool_call ids and function/schema names strip incidental whitespace over HTTP.

Form/JS SDKs sometimes pad OpenAI wire strings (``\" call_1 \"``,
``\" lookup_item \"``). After strip, length and ``[a-zA-Z0-9_-]`` charset still
fail closed; blank-after-strip remains omit/reject. Write-back keeps
passthrough on the canonical OpenAI form.
"""

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

_TEST_AUTH_TOKEN = "tool_call_id_name_strip_http_honesty_token"  # noqa: S105


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
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_padded_tool_calls_id_and_function_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "pad tool_calls"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "  call_pad_1  ",
                                "type": "function",
                                "function": {
                                    "name": "  lookup_item  ",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "  call_pad_1  ",
                        "content": "ok",
                    },
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_padded_tools_and_tool_choice_names() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "pad tools name"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "  lookup_item  ",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": "  lookup_item  "},
                },
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_padded_message_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "name": "  buyer_bot  ", "content": "pad name"}
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_padded_json_schema_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "pad schema name"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "  invoice_shape  ",
                        "schema": {"type": "object", "properties": {}},
                    },
                },
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_whitespace_only_tool_call_id() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "blank id"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "   ",
                                "type": "function",
                                "function": {"name": "lookup_item", "arguments": "{}"},
                            }
                        ],
                    },
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_illegal_name_after_strip() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bad name"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "  café  ",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_tools" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_padded_tool_calls_id_and_function_name()
    test_http_chat_accepts_padded_tools_and_tool_choice_names()
    test_http_chat_accepts_padded_message_name()
    test_http_chat_accepts_padded_json_schema_name()
    test_http_chat_still_rejects_whitespace_only_tool_call_id()
    test_http_chat_still_rejects_illegal_name_after_strip()
    print("ok")
