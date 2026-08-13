"""OpenAI Responses tools and tool_choice shape validation."""

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
    _validate_responses_tool_choice,
    _validate_responses_tools,
    build_server,
)

_TEST_AUTH_TOKEN = "resp_tools_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_responses_tools_shapes() -> None:
    assert _validate_responses_tools({}) is None
    nested = {
        "tools": [
            {
                "type": "function",
                "function": {"name": "lookup", "parameters": {"type": "object"}},
            }
        ]
    }
    assert len(_validate_responses_tools(nested) or []) == 1
    flat = {
        "tools": [
            {"type": "function", "name": "lookup", "parameters": {"type": "object"}},
            {"type": "web_search_preview"},
        ]
    }
    assert len(_validate_responses_tools(flat) or []) == 2
    try:
        _validate_responses_tools({"tools": []})
        raise AssertionError("empty")
    except RequestError as exc:
        assert exc.code == "invalid_tools"
    try:
        _validate_responses_tools({"tools": [{"type": "function"}]})
        raise AssertionError("missing name")
    except RequestError as exc:
        assert exc.code == "invalid_tools"


def test_validate_responses_tool_choice() -> None:
    assert _validate_responses_tool_choice({"tool_choice": "auto"}) == "auto"
    assert _validate_responses_tool_choice(
        {"tool_choice": {"type": "function", "function": {"name": "lookup"}}}
    )["type"] == "function"
    assert _validate_responses_tool_choice(
        {"tool_choice": {"type": "function", "name": "lookup"}}
    )["name"] == "lookup"
    try:
        _validate_responses_tool_choice({"tool_choice": "maybe"})
        raise AssertionError("bad string")
    except RequestError as exc:
        assert exc.code == "invalid_tool_choice"


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
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_responses_accepts_function_tools() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "use tools",
                "tools": [
                    {"type": "function", "name": "lookup", "parameters": {"type": "object"}},
                ],
                "tool_choice": "auto",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_bad_tools() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "use tools",
                "tools": [{"type": "function"}],
            },
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_tools"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_responses_tools_shapes()
    test_validate_responses_tool_choice()
    test_http_responses_accepts_function_tools()
    test_http_responses_rejects_bad_tools()
    print("ok")
