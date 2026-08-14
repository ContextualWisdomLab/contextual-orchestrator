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


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/responses",
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


def test_http_responses_accepts_valid_tools_and_auto_choice() -> None:
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
        assert status == 200, body
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


def test_http_responses_rejects_tool_choice_without_tools() -> None:
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
        assert status == 400, body
        assert "invalid_tool_choice" in json.dumps(body)
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
    test_http_responses_accepts_valid_tools_and_auto_choice()
    test_http_responses_rejects_empty_tools_array()
    test_http_responses_rejects_tool_without_function_type()
    test_http_responses_rejects_tool_choice_without_tools()
    test_http_responses_rejects_legacy_functions_surface()
    test_http_responses_rejects_named_tool_choice_not_in_tools()
    print("ok")
