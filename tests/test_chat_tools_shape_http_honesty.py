"""Chat Completions tools array shape honesty over HTTP (before passthrough)."""

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

_TEST_AUTH_TOKEN = "chat_tools_shape_http_honesty_token"  # noqa: S105


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


def _base_messages():
    return [{"role": "user", "content": "use a tool"}]


def test_http_chat_rejects_valid_function_tools_without_single_agent_fallback() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": _base_messages(),
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup_balance",
                            "description": "Fetch account balance",
                            "parameters": {
                                "type": "object",
                                "properties": {"account_id": {"type": "string"}},
                            },
                        },
                    }
                ],
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_empty_tools_array_as_noop() -> None:
    """SDKs often send tools: [] when no tools are configured — honest no-op."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": _base_messages(),
                "tools": [],
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_type_not_function() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": _base_messages(),
                "tools": [{"type": "code_interpreter", "function": {"name": "x"}}],
            },
        )
        assert status == 400, body
        assert "invalid_tools" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_missing_function_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": _base_messages(),
                "tools": [{"type": "function", "function": {"description": "no name"}}],
            },
        )
        assert status == 400, body
        assert "invalid_tools" in json.dumps(body)
        assert "name" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_function_name_bad_charset() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": _base_messages(),
                "tools": [
                    {
                        "type": "function",
                        "function": {"name": "bad name!"},
                    }
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_tools" in blob
        assert "a-zA-Z0-9" in blob or "match" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_sibling_unknown_fields() -> None:
    """Extra siblings on tool objects must fail closed, not silently pass through."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": _base_messages(),
                "tools": [
                    {
                        "type": "function",
                        "function": {"name": "lookup_balance"},
                        "extra_flag": True,
                    }
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_tools" in blob
        assert "only type and function" in blob or "extra_flag" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_parameters_non_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": _base_messages(),
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup_balance",
                            "parameters": "not-a-schema",
                        },
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_tools" in json.dumps(body)
        assert "parameters" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tools_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "no tools"}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)
