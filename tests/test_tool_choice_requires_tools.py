"""tool_choice requires tools; function_call requires functions."""

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
    _validate_tool_choice_requires_tools,
    build_server,
)

_TEST_AUTH_TOKEN = "tc_req_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_requires_tools() -> None:
    _validate_tool_choice_requires_tools({})
    _validate_tool_choice_requires_tools(
        {
            "tools": [{"type": "function", "function": {"name": "x", "parameters": {}}}],
            "tool_choice": "auto",
        }
    )
    try:
        _validate_tool_choice_requires_tools({"tool_choice": "auto"})
        raise AssertionError("expected invalid_tool_choice")
    except RequestError as exc:
        assert exc.code == "invalid_tool_choice"
    try:
        _validate_tool_choice_requires_tools({"function_call": "auto"})
        raise AssertionError("expected invalid_function_call")
    except RequestError as exc:
        assert exc.code == "invalid_function_call"


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


def test_http_chat_rejects_tool_choice_without_tools() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "tool_choice": "auto",
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_tool_choice"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_tool_choice_with_tools() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-generalist",
                "input": "hi",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ],
                "tool_choice": "auto",
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_requires_tools()
    test_http_chat_rejects_tool_choice_without_tools()
    test_http_responses_accepts_tool_choice_with_tools()
    print("ok")
