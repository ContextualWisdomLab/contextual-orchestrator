"""Empty/whitespace tool.function.description is omit-real over HTTP.

Official OpenAI SDKs serialize an omitted function description as ``""``
or a whitespace-only string. Leaving that key on the body is not
omit-equivalent: ``proxy_completion`` forwards it and several providers
treat a blank description as a malformed tool.

These cases assert the buyer-visible contract:

* chat and Responses return 200
* mock ``echo.tools`` no longer contains a blank ``description``
* non-empty descriptions stay on the payload
* non-string descriptions stay ``invalid_tools``
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

_TEST_AUTH_TOKEN = "tool_description_blank_omit_http_honesty_token"  # noqa: S105


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


def test_validate_chat_tools_pops_blank_description() -> None:
    body = {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "  \u00a0  ",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    }
    validated = _validate_chat_tools(body)
    assert validated is not None
    function = validated[0]["function"]
    assert "description" not in function
    assert "description" not in body["tools"][0]["function"]
    assert function.get("name") == "lookup"


def test_http_chat_omits_empty_tool_description() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "empty desc"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": "",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        assert status == 200, body
        function = _echo_function(body)
        assert "description" not in function
        assert function.get("parameters") == {"type": "object", "properties": {}}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_omits_whitespace_tool_description() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "blank desc"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": " \t ",
                        },
                    }
                ],
            },
        )
        assert status == 200, body
        assert "description" not in _echo_function(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_omits_blank_tool_description() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "responses blank desc",
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": "",
                            "parameters": None,
                        },
                    }
                ],
            },
        )
        assert status == 200, body
        function = _echo_function(body)
        assert "description" not in function
        assert "parameters" not in function
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_keeps_non_blank_tool_description() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "keep desc"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": "find things",
                        },
                    }
                ],
            },
        )
        assert status == 200, body
        assert _echo_function(body).get("description") == "find things"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_description_non_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "desc bad"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": ["not", "a", "string"],
                        },
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_tools" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_chat_tools_pops_blank_description()
    test_http_chat_omits_empty_tool_description()
    test_http_chat_omits_whitespace_tool_description()
    test_http_responses_omits_blank_tool_description()
    test_http_chat_keeps_non_blank_tool_description()
    test_http_chat_rejects_tool_description_non_string()
    print("ok")
