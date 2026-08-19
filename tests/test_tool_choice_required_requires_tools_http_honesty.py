"""tool_choice=required without tools fails closed over HTTP (chat + responses)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    build_server,
    _validate_chat_tool_choice,
)

_TEST_AUTH_TOKEN = "tool_choice_required_requires_tools_http_honesty_token"  # noqa: S105

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_balance",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_validate_tool_choice_required_without_tools_fails() -> None:
    try:
        _validate_chat_tool_choice({"tool_choice": "required"})
        raise AssertionError("expected RequestError")
    except RequestError as exc:
        assert exc.code == "invalid_tool_choice"
        assert "requires" in exc.message


def test_validate_tool_choice_required_empty_tools_fails() -> None:
    try:
        _validate_chat_tool_choice({"tool_choice": "required", "tools": []})
        raise AssertionError("expected RequestError")
    except RequestError as exc:
        assert exc.code == "invalid_tool_choice"


def test_validate_tool_choice_required_with_tools_ok() -> None:
    assert _validate_chat_tool_choice({"tool_choice": "required", "tools": _TOOLS}) == "required"


def test_http_chat_rejects_tool_choice_required_without_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "required no tools"}],
                "tool_choice": "required",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_tool_choice" in blob
        assert "unknown_fields" not in blob
        assert "requires" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_choice_required_with_empty_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "required empty tools"}],
                "tools": [],
                "tool_choice": "required",
            },
        )
        assert status == 400, body
        assert "invalid_tool_choice" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_choice_required_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "required with tools"}],
                "tools": _TOOLS,
                "tool_choice": "required",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_tool_choice_required_without_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "required no tools on responses",
                "tool_choice": "required",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_tool_choice" in blob
        assert "requires" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_tool_choice_required_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "required with tools on responses",
                "tools": _TOOLS,
                "tool_choice": "required",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_tool_choice_required_without_tools_fails()
    test_validate_tool_choice_required_empty_tools_fails()
    test_validate_tool_choice_required_with_tools_ok()
    test_http_chat_rejects_tool_choice_required_without_tools()
    test_http_chat_rejects_tool_choice_required_with_empty_tools()
    test_http_chat_accepts_tool_choice_required_with_tools()
    test_http_responses_rejects_tool_choice_required_without_tools()
    test_http_responses_accepts_tool_choice_required_with_tools()
    print("ok")
