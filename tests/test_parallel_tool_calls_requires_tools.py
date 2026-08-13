"""parallel_tool_calls=true requires a non-empty tools array."""

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
    _validate_parallel_tool_calls_requires_tools,
    build_server,
)

_TEST_AUTH_TOKEN = "ptc_req_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_parallel_tool_calls_requires_tools() -> None:
    _validate_parallel_tool_calls_requires_tools({})
    _validate_parallel_tool_calls_requires_tools({"parallel_tool_calls": False})
    _validate_parallel_tool_calls_requires_tools(
        {
            "parallel_tool_calls": True,
            "tools": [{"type": "function", "function": {"name": "x", "parameters": {}}}],
        }
    )
    try:
        _validate_parallel_tool_calls_requires_tools({"parallel_tool_calls": True})
        raise AssertionError("expected invalid_parallel_tool_calls")
    except RequestError as exc:
        assert exc.code == "invalid_parallel_tool_calls"
    try:
        _validate_parallel_tool_calls_requires_tools(
            {"parallel_tool_calls": True, "tools": []}
        )
        raise AssertionError("expected invalid_parallel_tool_calls empty tools")
    except RequestError as exc:
        assert exc.code == "invalid_parallel_tool_calls"


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


def test_http_chat_rejects_parallel_tool_calls_without_tools() -> None:
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
                "parallel_tool_calls": True,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_parallel_tool_calls"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_parallel_tool_calls_with_tools() -> None:
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
                "parallel_tool_calls": True,
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ],
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_parallel_tool_calls_requires_tools()
    test_http_chat_rejects_parallel_tool_calls_without_tools()
    test_http_responses_accepts_parallel_tool_calls_with_tools()
    print("ok")
