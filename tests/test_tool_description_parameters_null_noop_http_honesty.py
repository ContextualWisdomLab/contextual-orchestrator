"""tool.function description/parameters/strict null are omit-real over HTTP.

SDK optional defaults often serialize omitted fields as JSON null. Accepting
those keys without popping them is not omit-equivalent: ``proxy_completion``
forwards the body to the provider, and several OpenAI-compatible backends
reject ``parameters: null`` / ``description: null`` as non-objects.

These cases assert the buyer-visible contract:

* chat and Responses return 200
* mock ``echo.tools`` no longer contains the null keys
* non-null wrong types stay fail-closed with named ``invalid_tools``
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

_TEST_AUTH_TOKEN = "tool_description_parameters_null_noop_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    """Return a single-mock-agent orchestrator for isolated HTTP honesty probes."""
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    """POST JSON to a loopback server and return status plus decoded body."""
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
    """Start a daemon stdlib server on an ephemeral port."""
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _echo_function(body: dict) -> dict:
    """Return the first echoed tool.function object from a mock passthrough."""
    echo = body.get("echo") or {}
    tools = echo.get("tools") or []
    assert tools, body
    function = tools[0].get("function")
    assert isinstance(function, dict), body
    return function


def test_validate_chat_tools_pops_null_optional_function_fields() -> None:
    """Null optional fields must disappear from the request body before proxy."""
    body = {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": None,
                    "parameters": None,
                    "strict": None,
                },
            }
        ]
    }
    validated = _validate_chat_tools(body)
    assert validated is not None
    function = validated[0]["function"]
    assert "description" not in function
    assert "parameters" not in function
    assert "strict" not in function
    assert "description" not in body["tools"][0]["function"]
    assert "parameters" not in body["tools"][0]["function"]
    assert "strict" not in body["tools"][0]["function"]
    assert function["name"] == "lookup"


def test_http_chat_omits_tool_description_null() -> None:
    """Chat passthrough must drop description:null so providers see omit."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "desc null"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": None,
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        assert status == 200, body
        function = _echo_function(body)
        assert "description" not in function
        assert function["parameters"] == {"type": "object", "properties": {}}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_omits_tool_parameters_null() -> None:
    """Chat passthrough must drop parameters:null so providers see omit."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "params null"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": None,
                        },
                    }
                ],
            },
        )
        assert status == 200, body
        function = _echo_function(body)
        assert "parameters" not in function
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_omits_tool_description_parameters_and_strict_null() -> None:
    """Combined SDK nulls must all be absent from the forwarded tools payload."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "both null"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": None,
                            "parameters": None,
                            "strict": None,
                        },
                    }
                ],
            },
        )
        assert status == 200, body
        function = _echo_function(body)
        assert "description" not in function
        assert "parameters" not in function
        assert "strict" not in function
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_omits_tool_description_and_parameters_null() -> None:
    """Responses passthrough shares the validator and must omit-real the same keys."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "responses null tools",
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": None,
                            "parameters": None,
                            "strict": None,
                        },
                    }
                ],
            },
        )
        assert status == 200, body
        function = _echo_function(body)
        assert "description" not in function
        assert "parameters" not in function
        assert "strict" not in function
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_description_non_string() -> None:
    """A numeric description is not an SDK default and must stay invalid_tools."""
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
                            "description": 123,
                            "parameters": {"type": "object", "properties": {}},
                        },
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


def test_http_chat_rejects_tool_parameters_non_object() -> None:
    """A string parameters value is not an SDK default and must stay invalid_tools."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "params bad"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": "not-an-object",
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
    test_validate_chat_tools_pops_null_optional_function_fields()
    test_http_chat_omits_tool_description_null()
    test_http_chat_omits_tool_parameters_null()
    test_http_chat_omits_tool_description_parameters_and_strict_null()
    test_http_responses_omits_tool_description_and_parameters_null()
    test_http_chat_rejects_tool_description_non_string()
    test_http_chat_rejects_tool_parameters_non_object()
    print("ok")
