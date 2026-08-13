"""OpenAI response_format and tool_choice shape validation on chat completions."""

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
    _validate_response_format,
    _validate_tool_choice,
    build_server,
)

_TEST_AUTH_TOKEN = "rf_tc_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_response_format() -> None:
    assert _validate_response_format({}) is None
    assert _validate_response_format({"response_format": {"type": "json_object"}})["type"] == "json_object"
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "answer_schema",
            "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        },
    }
    assert _validate_response_format({"response_format": schema}) == schema
    try:
        _validate_response_format({"response_format": "json"})
        raise AssertionError("expected invalid_response_format")
    except RequestError as exc:
        assert exc.code == "invalid_response_format"
    try:
        _validate_response_format({"response_format": {"type": "xml"}})
        raise AssertionError("expected invalid_response_format type")
    except RequestError as exc:
        assert exc.code == "invalid_response_format"
    try:
        _validate_response_format(
            {"response_format": {"type": "json_schema", "json_schema": {"name": "x"}}}
        )
        raise AssertionError("expected invalid_response_format schema")
    except RequestError as exc:
        assert exc.code == "invalid_response_format"


def test_validate_tool_choice() -> None:
    assert _validate_tool_choice({}) is None
    assert _validate_tool_choice({"tool_choice": "auto"}) == "auto"
    assert _validate_tool_choice({"tool_choice": "required"}) == "required"
    named = {"type": "function", "function": {"name": "lookup_item"}}
    assert _validate_tool_choice({"tool_choice": named}) == named
    try:
        _validate_tool_choice({"tool_choice": "maybe"})
        raise AssertionError("expected invalid_tool_choice string")
    except RequestError as exc:
        assert exc.code == "invalid_tool_choice"
    try:
        _validate_tool_choice({"tool_choice": {"type": "tool", "function": {"name": "x"}}})
        raise AssertionError("expected invalid_tool_choice type")
    except RequestError as exc:
        assert exc.code == "invalid_tool_choice"
    try:
        _validate_tool_choice({"tool_choice": {"type": "function", "function": {"name": ""}}})
        raise AssertionError("expected invalid_tool_choice name")
    except RequestError as exc:
        assert exc.code == "invalid_tool_choice"


def test_http_response_format_accepted() -> None:
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
                    "response_format": {"type": "json_object"},
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
    assert body.get("echo", {}).get("response_format", {}).get("type") == "json_object"


def test_http_tool_choice_invalid_rejected() -> None:
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
                    "tool_choice": "sometimes",
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
            assert body["error"]["code"] == "invalid_tool_choice"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_response_format()
    test_validate_tool_choice()
    test_http_response_format_accepted()
    test_http_tool_choice_invalid_rejected()
    print("ok")
