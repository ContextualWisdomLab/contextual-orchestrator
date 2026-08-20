"""Chat tools honesty: unsupported legacy and multi-agent tool surfaces fail closed."""

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

_TEST_AUTH_TOKEN = "chat_tool_choice_functions_http_honesty_token"  # noqa: S105

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_invoice",
            "description": "Look up invoice by id",
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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_rejects_functions_legacy_surface() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "lookup invoice 9"}],
                "functions": [
                    {
                        "name": "lookup_invoice",
                        "description": "legacy",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_functions" in blob
        assert "tools" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_function_call_auto_without_functions_migration() -> None:
    """Legacy function_call is rejected even when it does not name a function."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "lookup invoice 9"}],
                "function_call": "auto",
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_function_call_named_without_tools_migration() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "lookup invoice 9"}],
                "function_call": {"name": "lookup"},
            },
        )
        assert status == 400, body
        assert "invalid_functions" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_choice_auto_without_tools_migration() -> None:
    """Chat tool choice cannot be represented by the multi-agent contract."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "hi"}],
                "tool_choice": "auto",
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tools_with_tool_choice_passthrough() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "lookup invoice 9"}],
                "tools": _TOOLS,
                "tool_choice": "auto",
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_functions_legacy_surface()
    test_http_chat_rejects_function_call_auto_without_functions_migration()
    test_http_chat_rejects_function_call_named_without_tools_migration()
    test_http_chat_rejects_tool_choice_auto_without_tools_migration()
    test_http_chat_rejects_tools_with_tool_choice_passthrough()
    print("ok")
