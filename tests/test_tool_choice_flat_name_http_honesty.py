"""Responses flat tool_choice {type,name} alongside chat nested over HTTP."""

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

_TEST_AUTH_TOKEN = "tool_choice_flat_name_http_honesty_token"  # noqa: S105


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


def test_http_responses_rejects_flat_tool_choice_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "flat tool_choice",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup_item",
                        "parameters": {"type": "object"},
                    }
                ],
                "tool_choice": {"type": "function", "name": "lookup_item"},
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_flat_tool_choice_padded_casefold() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "flat tool_choice pad",
                "tools": [
                    {
                        "type": "FUNCTION",
                        "name": " lookup_item ",
                        "parameters": {"type": "object"},
                    }
                ],
                "tool_choice": {"type": " FUNCTION ", "name": " lookup_item "},
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_flat_tool_choice_with_nested_tools() -> None:
    """Chat clients using Responses-flat tool_choice against nested tools."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "flat choice nested tools"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup_item",
                            "parameters": {"type": "object"},
                        },
                    }
                ],
                "tool_choice": {"type": "function", "name": "lookup_item"},
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_nested_tool_choice() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "nested choice"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup_item",
                            "parameters": {"type": "object"},
                        },
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": "lookup_item"},
                },
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tool_choice_rejects_mixed_nested_and_flat() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "mixed choice",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup_item",
                        "parameters": {"type": "object"},
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "name": "lookup_item",
                    "function": {"name": "lookup_item"},
                },
            },
        )
        assert status == 400, body
        assert "invalid_tool_choice" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_flat_tool_choice_unknown_name_fails_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "unknown name"}],
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup_item",
                        "parameters": {"type": "object"},
                    }
                ],
                "tool_choice": {"type": "function", "name": "other_tool"},
            },
        )
        assert status == 400, body
        assert "invalid_tool_choice" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_rejects_flat_tool_choice_name()
    test_http_responses_rejects_flat_tool_choice_padded_casefold()
    test_http_chat_rejects_flat_tool_choice_with_nested_tools()
    test_http_chat_rejects_nested_tool_choice()
    test_http_tool_choice_rejects_mixed_nested_and_flat()
    test_http_flat_tool_choice_unknown_name_fails_closed()
    print("ok")
