"""Chat Completions tool_choice must be none/auto/required or function object."""

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

_TEST_AUTH_TOKEN = "chat_tool_choice_type_token"  # noqa: S105

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "lookup",
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


def test_http_chat_rejects_invalid_tool_choice_string() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "tools": _TOOLS,
                "tool_choice": "maybe",
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_tool_choice"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_choice_object_without_name() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "tools": _TOOLS,
                "tool_choice": {"type": "function", "function": {}},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_tool_choice"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_string_non_object_tool_choice() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "tools": _TOOLS,
                "tool_choice": 1,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_tool_choice"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_choice_auto_with_tools() -> None:
    """Valid shape reaches passthrough (mock may still 200 or provider-shaped error)."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "tools": _TOOLS,
                "tool_choice": "auto",
            },
        )
        if status == 400:
            assert body.get("error", {}).get("code") != "invalid_tool_choice", body
        else:
            assert status in (200, 502, 503), body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_invalid_tool_choice_string()
    test_http_chat_rejects_tool_choice_object_without_name()
    test_http_chat_rejects_non_string_non_object_tool_choice()
    test_http_chat_accepts_tool_choice_auto_with_tools()
