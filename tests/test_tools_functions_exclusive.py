"""tools/functions and tool_choice/function_call mutual exclusion."""

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
    _validate_tools_functions_exclusive,
    build_server,
)

_TEST_AUTH_TOKEN = "tf_excl_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_tools_functions_exclusive() -> None:
    _validate_tools_functions_exclusive({})
    _validate_tools_functions_exclusive(
        {"tools": [{"type": "function", "function": {"name": "a"}}]}
    )
    _validate_tools_functions_exclusive(
        {"functions": [{"name": "a", "parameters": {}}]}
    )
    try:
        _validate_tools_functions_exclusive(
            {
                "tools": [{"type": "function", "function": {"name": "a"}}],
                "functions": [{"name": "b", "parameters": {}}],
            }
        )
        raise AssertionError("expected invalid_request tools+functions")
    except RequestError as exc:
        assert exc.code == "invalid_request"
    try:
        _validate_tools_functions_exclusive(
            {"tool_choice": "auto", "function_call": "auto"}
        )
        raise AssertionError("expected invalid_request choices")
    except RequestError as exc:
        assert exc.code == "invalid_request"
    try:
        _validate_tools_functions_exclusive(
            {
                "functions": [{"name": "a", "parameters": {}}],
                "tool_choice": "auto",
            }
        )
        raise AssertionError("expected invalid_request tool_choice+functions")
    except RequestError as exc:
        assert exc.code == "invalid_request"
    try:
        _validate_tools_functions_exclusive(
            {
                "tools": [{"type": "function", "function": {"name": "a"}}],
                "function_call": "auto",
            }
        )
        raise AssertionError("expected invalid_request function_call+tools")
    except RequestError as exc:
        assert exc.code == "invalid_request"


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


def test_http_rejects_tools_with_functions() -> None:
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
                "functions": [
                    {"name": "legacy_fn", "parameters": {"type": "object", "properties": {}}}
                ],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_request"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_tools_alone() -> None:
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
    test_validate_tools_functions_exclusive()
    test_http_rejects_tools_with_functions()
    test_http_accepts_tools_alone()
    print("ok")
