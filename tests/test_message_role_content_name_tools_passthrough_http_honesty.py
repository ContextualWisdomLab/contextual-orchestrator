"""Tools passthrough must fail-closed on role, content shape, and message name.

``_validate_messages`` is skipped when ``tools`` / ``response_format`` force
single-agent passthrough. Role membership, developer-role migration, content
shape, participant ``name``, and a non-empty ``messages`` array must still
run before the body is proxied so SDK tool-calling histories cannot smuggle
unsupported values or bill a completion with no prompt.
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

_TEST_AUTH_TOKEN = "message_role_content_name_tools_passthrough_token"  # noqa: S105

_LOOKUP_TOOLS = [
    {
        "type": "function",
        "function": {"name": "lookup_balance", "parameters": {"type": "object"}},
    }
]


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


def test_http_chat_rejects_developer_role_with_tools() -> None:
    """Newer OpenAI SDKs send developer + tools; must not proxy as system."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "developer", "content": "system-like instructions"},
                    {"role": "user", "content": "look up the invoice"},
                ],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message_role" in blob
        assert "developer" in blob
        assert "system" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_empty_user_content_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "   "}],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_input_audio_content_part_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {"data": "AAAA", "format": "wav"},
                            }
                        ],
                    }
                ],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_empty_message_name_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "named tool turn", "name": "   "},
                ],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message_name" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_name_on_tool_message_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "run tool"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "lookup_balance",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "content": "ok",
                        "tool_call_id": "call_1",
                        "name": "should_not_be_here",
                    },
                ],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message_name" in blob
        assert "tool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_empty_messages_with_tools() -> None:
    """SDK tool-calling bodies must not bill a completion with no prompt."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "non-empty" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_omitted_messages_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "non-empty" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_null_messages_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": None,
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "non-empty" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_list_messages_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": "look up the invoice",
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "non-empty" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_empty_messages_with_response_format() -> None:
    """response_format is the other PASSTHROUGH_TRIGGER_KEYS early-return."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "non-empty" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_developer_role_with_tools()
    test_http_chat_rejects_empty_user_content_with_tools()
    test_http_chat_rejects_input_audio_content_part_with_tools()
    test_http_chat_rejects_empty_message_name_with_tools()
    test_http_chat_rejects_name_on_tool_message_with_tools()
    test_http_chat_rejects_empty_messages_with_tools()
    test_http_chat_rejects_omitted_messages_with_tools()
    test_http_chat_rejects_null_messages_with_tools()
    test_http_chat_rejects_non_list_messages_with_tools()
    test_http_chat_rejects_empty_messages_with_response_format()
    print("ok")
