"""Chat parallel_tool_calls honesty: boolean type; true requires tools."""

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

_TEST_AUTH_TOKEN = "chat_parallel_tool_calls_honesty_token"  # noqa: S105

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_invoice",
            "description": "Look up an invoice by id",
            "parameters": {
                "type": "object",
                "properties": {"invoice_id": {"type": "string"}},
                "required": ["invoice_id"],
            },
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
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_parallel_tool_calls_false_without_tools_ok() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "parallel_tool_calls": False,
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_parallel_tool_calls_true_without_tools_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "parallel_tool_calls": True,
            },
        )
        assert status == 400, body
        assert "invalid_parallel_tool_calls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_parallel_tool_calls_non_boolean_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "parallel_tool_calls": "yes",
            },
        )
        assert status == 400, body
        assert "invalid_parallel_tool_calls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_parallel_tool_calls_true_with_tools_passthrough() -> None:
    """With tools, parallel_tool_calls triggers single-agent passthrough path."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "lookup invoice 42"}],
                "tools": _TOOLS,
                "parallel_tool_calls": True,
            },
        )
        # Mock passthrough returns chat-shaped body
        assert status == 200, body
        assert "choices" in body or "id" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_parallel_tool_calls_false_without_tools_ok()
    test_http_chat_parallel_tool_calls_true_without_tools_fail_closed()
    test_http_chat_parallel_tool_calls_non_boolean_fail_closed()
    test_http_chat_parallel_tool_calls_true_with_tools_passthrough()
    print("ok")
