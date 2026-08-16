"""Responses-native function tools are accepted on /v1/responses only.

Official Responses SDKs send top-level ``name`` / ``parameters`` / ``strict``
instead of a nested ``function`` object (OpenAI, 2024c). Chat stays chat-shaped.
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

_TEST_AUTH_TOKEN = "responses_native_tools_http_honesty_token"  # noqa: S105


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


def _responses_native_tool(*, strict: bool | None) -> dict:
    return {
        "type": "function",
        "name": "lookup_item",
        "description": "look up an item",
        "parameters": {"type": "object", "properties": {}},
        "strict": strict,
    }


def test_http_responses_accepts_native_tool_and_pops_strict_null() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "native tool strict null",
                "parallel_tool_calls": True,
                "tools": [_responses_native_tool(strict=None)],
            },
        )
        assert status == 200, body
        echoed = body["echo"]["tools"][0]
        assert echoed["name"] == "lookup_item"
        assert "function" not in echoed
        assert "strict" not in echoed, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_forwards_native_tool_strict_true() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "native tool strict true",
                "tools": [_responses_native_tool(strict=True)],
            },
        )
        assert status == 200, body
        assert body["echo"]["tools"][0]["strict"] is True
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_native_tool_unknown_field() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "native tool extra",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup_item",
                        "parameters": {"type": "object", "properties": {}},
                        "extra_flag": True,
                    }
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_tools" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_ambiguous_chat_and_native_tool() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "ambiguous tool",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup_item",
                        "function": {"name": "lookup_item"},
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_tools" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_native_named_tool_choice() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "native named choice",
                "tools": [_responses_native_tool(strict=False)],
                "tool_choice": {"type": "function", "name": "lookup_item"},
            },
        )
        assert status == 200, body
        assert body["echo"]["tool_choice"]["name"] == "lookup_item"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_native_named_tool_choice_mismatch() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "native named missing",
                "tools": [_responses_native_tool(strict=False)],
                "tool_choice": {"type": "function", "name": "not_declared"},
            },
        )
        assert status == 400, body
        assert "invalid_tool_choice" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_responses_native_tool_shape() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "native tool on chat"}],
                "tools": [_responses_native_tool(strict=None)],
            },
        )
        assert status == 400, body
        assert "invalid_tools" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_accepts_native_tool_and_pops_strict_null()
    test_http_responses_forwards_native_tool_strict_true()
    test_http_responses_rejects_native_tool_unknown_field()
    test_http_responses_rejects_ambiguous_chat_and_native_tool()
    test_http_responses_accepts_native_named_tool_choice()
    test_http_responses_rejects_native_named_tool_choice_mismatch()
    test_http_chat_rejects_responses_native_tool_shape()
    print("ok")
