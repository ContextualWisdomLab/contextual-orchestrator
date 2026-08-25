"""Responses tools / tool_choice shape honesty over HTTP (fail-closed)."""

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

_TEST_AUTH_TOKEN = "responses_tools_shape_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict, *, tool_loop: bool = False) -> tuple[int, dict]:
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
        "connection": "close",
    }
    if tool_loop:
        headers["x-contextual-orchestrator-tool-loop"] = "v1"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
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


def _valid_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup_item",
                "description": "look up an item",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_http_responses_rejects_tools_without_explicit_loop_header() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "use tools",
                "tools": _valid_tools(),
                "tool_choice": "auto",
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_preserves_tools_with_explicit_loop_header() -> None:
    """The opt-in Responses contract preserves the provider response shape."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "use tools",
                "tools": _valid_tools(),
                "tool_choice": "auto",
            },
            tool_loop=True,
        )
        assert status == 200, body
        assert body["echo"]["tools"] == _valid_tools()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_tool_loop_rejects_stream_true() -> None:
    """Client-owned Responses tool loops must reject unsupported streaming."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "stream tools",
                "tools": _valid_tools(),
                "stream": True,
            },
            tool_loop=True,
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_stream"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_tool_loop_requires_input() -> None:
    """Client-owned Responses tool loops still require a non-empty input."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "tools": _valid_tools()},
            tool_loop=True,
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_input"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_tool_loop_rejects_scalar_input() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "input": 7, "tools": _valid_tools()},
            tool_loop=True,
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_input"
    finally:
        server.shutdown()
        thread.join(timeout=5)

def test_http_responses_accepts_empty_tools_array_as_noop() -> None:
    """SDKs often send tools: [] when no tools are configured — honest no-op."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "input": "tools empty", "tools": []},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_tool_without_function_type() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "bad tool type",
                "tools": [{"type": "retrieval", "function": {"name": "x"}}],
            },
        )
        assert status == 400, body
        assert "invalid_tools" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_tool_choice_auto_without_tools_as_omit() -> None:
    """tool_choice auto/none without tools is an omit-equivalent no-op."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "choice alone",
                "tool_choice": "auto",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_legacy_functions_surface() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "legacy functions",
                "functions": [{"name": "lookup_item", "parameters": {}}],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_functions" in blob
        assert "tools" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_named_tool_choice_not_in_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "named missing",
                "tools": _valid_tools(),
                "tool_choice": {
                    "type": "function",
                    "function": {"name": "not_declared"},
                },
            },
        )
        assert status == 400, body
        assert "invalid_tool_choice" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_rejects_tools_without_explicit_loop_header()
    test_http_responses_preserves_tools_with_explicit_loop_header()
    test_http_responses_tool_loop_rejects_stream_true()
    test_http_responses_tool_loop_requires_input()
    test_http_responses_accepts_empty_tools_array_as_noop()
    test_http_responses_rejects_tool_without_function_type()
    test_http_responses_accepts_tool_choice_auto_without_tools_as_omit()
    test_http_responses_rejects_legacy_functions_surface()
    test_http_responses_rejects_named_tool_choice_not_in_tools()
    print("ok")
