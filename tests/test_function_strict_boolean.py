"""OpenAI tools[].function.strict and functions[].strict must be booleans."""

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
    _validate_function_strict_flags,
    build_server,
)

_TEST_AUTH_TOKEN = "function_strict_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _sample_tools(*, strict: object = True) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup_item",
                "strict": strict,
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_validate_function_strict_flags() -> None:
    _validate_function_strict_flags({})
    _validate_function_strict_flags({"tools": _sample_tools(strict=True)})
    _validate_function_strict_flags({"tools": _sample_tools(strict=False)})
    _validate_function_strict_flags(
        {"functions": [{"name": "lookup_item", "strict": True, "parameters": {"type": "object"}}]}
    )
    try:
        _validate_function_strict_flags({"tools": _sample_tools(strict="yes")})
        raise AssertionError("expected invalid_function_strict on tools")
    except RequestError as exc:
        assert exc.code == "invalid_function_strict"
    try:
        _validate_function_strict_flags(
            {"functions": [{"name": "lookup_item", "strict": 1}]}
        )
        raise AssertionError("expected invalid_function_strict on functions")
    except RequestError as exc:
        assert exc.code == "invalid_function_strict"
    # Missing strict is fine; non-dict entries are skipped (shape validators own that).
    _validate_function_strict_flags({"tools": ["not-an-object"]})
    _validate_function_strict_flags(
        {"tools": [{"type": "function", "function": {"name": "x"}}]}
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
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_rejects_non_boolean_tool_strict() -> None:
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
                "tools": _sample_tools(strict="true"),
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_function_strict"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_boolean_tool_strict() -> None:
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
                "tools": _sample_tools(strict=True),
            },
        )
        assert status == 200, body
        assert body.get("choices") or body.get("object")
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_function_strict_flags()
    test_http_rejects_non_boolean_tool_strict()
    test_http_accepts_boolean_tool_strict()
