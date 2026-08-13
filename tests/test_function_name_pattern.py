"""OpenAI function name pattern ^[a-zA-Z0-9_-]{1,64}$ validation."""

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
    _validate_function_names,
    build_server,
)

_TEST_AUTH_TOKEN = "fn_name_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_function_names() -> None:
    _validate_function_names({})
    _validate_function_names(
        {
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "get_weather", "parameters": {"type": "object"}},
                }
            ]
        }
    )
    _validate_function_names({"functions": [{"name": "lookup_user", "parameters": {}}]})
    try:
        _validate_function_names(
            {
                "tools": [
                    {
                        "type": "function",
                        "function": {"name": "bad name!", "parameters": {}},
                    }
                ]
            }
        )
        raise AssertionError("expected invalid_function_name")
    except RequestError as exc:
        assert exc.code == "invalid_function_name"
    try:
        _validate_function_names({"functions": [{"name": "x" * 65, "parameters": {}}]})
        raise AssertionError("expected invalid_function_name length")
    except RequestError as exc:
        assert exc.code == "invalid_function_name"
    try:
        _validate_function_names(
            {"tool_choice": {"type": "function", "function": {"name": "has space"}}}
        )
        raise AssertionError("expected invalid_function_name tool_choice")
    except RequestError as exc:
        assert exc.code == "invalid_function_name"


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
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


def test_http_rejects_invalid_function_name() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get weather",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_function_name"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_valid_function_name() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        assert status == 200, body
        assert body["choices"][0]["message"]["content"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_function_names()
    test_http_rejects_invalid_function_name()
    test_http_accepts_valid_function_name()
    print("ok")
