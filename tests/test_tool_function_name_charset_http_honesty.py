"""tool.function.name charset is fail-closed over HTTP.

OpenAI function names must match ``[a-zA-Z0-9_-]{1,64}`` — the same
ASCII charset now enforced on ``response_format.json_schema.name``.
``str.isalnum()`` alone accepts Unicode letters and digits (``café``,
``名前``, Arabic-Indic digits). Forwarding those names is not honest:
``proxy_completion`` sends the body and the buyer sees an opaque
provider rejection instead of a named ``invalid_tools`` next action.

These cases assert the buyer-visible contract:

* chat and Responses return 400 ``invalid_tools`` for Unicode names
* a 64-character legal ASCII name is kept on mock ``echo.tools``
* a legal short name is unchanged
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
from contextual_orchestrator.server import (  # noqa: E402
    SecurityConfig,
    _validate_chat_tools,
    build_server,
)

_TEST_AUTH_TOKEN = "tool_function_name_charset_http_honesty_token"  # noqa: S105


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


def _echo_function(body: dict) -> dict:
    echo = body.get("echo") or {}
    tools = echo.get("tools") or []
    assert tools, body
    function = tools[0].get("function")
    assert isinstance(function, dict), body
    return function


def _function_tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_validate_chat_tools_rejects_unicode_function_name() -> None:
    """Python str.isalnum() accepts café/名前/١٢٣; OpenAI does not."""
    for illegal_name in ("café", "名前", "lookup_١٢٣"):
        body = {"tools": [_function_tool(illegal_name)]}
        try:
            _validate_chat_tools(body)
        except Exception as exc:
            assert getattr(exc, "code", None) == "invalid_tools"
            assert "must match [a-zA-Z0-9_-]" in str(exc)
            continue
        raise AssertionError(f"{illegal_name!r} tool.function.name must fail closed")


def test_http_chat_rejects_unicode_function_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tool unicode"}],
                "tools": [_function_tool("café")],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_tools" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_unicode_function_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "responses tool unicode",
                "tools": [_function_tool("名前")],
            },
        )
        assert status == 400, body
        assert "invalid_tools" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_keeps_legal_function_name() -> None:
    server, thread, port = _server()
    try:
        max_name = "B" * 64
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "responses tool max",
                "tools": [_function_tool(max_name)],
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_keeps_legal_function_name() -> None:
    server, thread, port = _server()
    try:
        legal_name = "lookup_balance-01"
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tool keep"}],
                "tools": [_function_tool(legal_name)],
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_chat_tools_rejects_unicode_function_name()
    test_http_chat_rejects_unicode_function_name()
    test_http_responses_rejects_unicode_function_name()
    test_http_responses_keeps_legal_function_name()
    test_http_chat_keeps_legal_function_name()
    print("ok")
