"""Tool/function description strings capped at 1024 characters."""

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
    _MAX_FUNCTION_DESCRIPTION_CHARS,
    _validate_function_descriptions,
    build_server,
)

_TEST_AUTH_TOKEN = "fn_desc_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_function_descriptions() -> None:
    assert _MAX_FUNCTION_DESCRIPTION_CHARS == 1024
    _validate_function_descriptions({})
    _validate_function_descriptions(
        {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "ok",
                        "parameters": {"type": "object"},
                    },
                }
            ]
        }
    )
    try:
        _validate_function_descriptions(
            {
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "description": "x" * 1025,
                            "parameters": {"type": "object"},
                        },
                    }
                ]
            }
        )
        raise AssertionError("expected invalid_tools")
    except RequestError as exc:
        assert exc.code == "invalid_tools"
    try:
        _validate_function_descriptions(
            {"functions": [{"name": "legacy", "description": 12, "parameters": {}}]}
        )
        raise AssertionError("expected invalid_functions")
    except RequestError as exc:
        assert exc.code == "invalid_functions"


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


def test_http_rejects_long_tool_description() -> None:
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
                            "description": "d" * 1025,
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_tools"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_description_at_cap() -> None:
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
                            "description": "e" * 1024,
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
    test_validate_function_descriptions()
    test_http_rejects_long_tool_description()
    test_http_accepts_description_at_cap()
    print("ok")
