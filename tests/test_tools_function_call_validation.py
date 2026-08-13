"""OpenAI tools array and legacy function_call shape validation."""

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
    _validate_function_call,
    _validate_tools,
    build_server,
)

_TEST_AUTH_TOKEN = "tools_fc_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _sample_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup_item",
                "description": "Look up a catalog item by id",
                "parameters": {
                    "type": "object",
                    "properties": {"item_id": {"type": "string"}},
                    "required": ["item_id"],
                },
            },
        }
    ]


def test_validate_tools() -> None:
    assert _validate_tools({}) is None
    tools = _sample_tools()
    assert _validate_tools({"tools": tools}) == tools
    try:
        _validate_tools({"tools": []})
        raise AssertionError("expected invalid_tools empty")
    except RequestError as exc:
        assert exc.code == "invalid_tools"
    try:
        _validate_tools({"tools": [{"type": "api", "function": {"name": "x"}}]})
        raise AssertionError("expected invalid_tools type")
    except RequestError as exc:
        assert exc.code == "invalid_tools"
    try:
        _validate_tools({"tools": [{"type": "function", "function": {"name": ""}}]})
        raise AssertionError("expected invalid_tools name")
    except RequestError as exc:
        assert exc.code == "invalid_tools"
    try:
        _validate_tools(
            {
                "tools": [
                    {
                        "type": "function",
                        "function": {"name": "x", "parameters": "not-object"},
                    }
                ]
            }
        )
        raise AssertionError("expected invalid_tools parameters")
    except RequestError as exc:
        assert exc.code == "invalid_tools"


def test_validate_function_call() -> None:
    assert _validate_function_call({}) is None
    assert _validate_function_call({"function_call": "auto"}) == "auto"
    assert _validate_function_call({"function_call": {"name": "lookup_item"}})["name"] == "lookup_item"
    try:
        _validate_function_call({"function_call": "required"})
        raise AssertionError("expected invalid_function_call string")
    except RequestError as exc:
        assert exc.code == "invalid_function_call"
    try:
        _validate_function_call({"function_call": {"name": ""}})
        raise AssertionError("expected invalid_function_call name")
    except RequestError as exc:
        assert exc.code == "invalid_function_call"
    try:
        _validate_function_call({"function_call": 1})
        raise AssertionError("expected invalid_function_call type")
    except RequestError as exc:
        assert exc.code == "invalid_function_call"


def test_http_tools_accepted_via_passthrough() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "find item-42"}],
                    "tools": _sample_tools(),
                    "tool_choice": "auto",
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert body["object"] == "chat.completion"
    assert body.get("echo", {}).get("tools", [{}])[0].get("function", {}).get("name") == "lookup_item"


def test_http_invalid_tools_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "tools": [{"type": "function", "function": {}}],
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert body["error"]["code"] == "invalid_tools"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_tools()
    test_validate_function_call()
    test_http_tools_accepted_via_passthrough()
    test_http_invalid_tools_rejected()
    print("ok")
