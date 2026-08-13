"""OpenAI parallel_tool_calls boolean validation."""

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
    _validate_parallel_tool_calls,
    build_server,
)

_TEST_AUTH_TOKEN = "ptc_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_parallel_tool_calls() -> None:
    assert _validate_parallel_tool_calls({}) is None
    assert _validate_parallel_tool_calls({"parallel_tool_calls": True}) is True
    assert _validate_parallel_tool_calls({"parallel_tool_calls": False}) is False
    try:
        _validate_parallel_tool_calls({"parallel_tool_calls": "yes"})
        raise AssertionError("expected invalid_parallel_tool_calls")
    except RequestError as exc:
        assert exc.code == "invalid_parallel_tool_calls"


def test_http_parallel_tool_calls_false_with_tools_passthrough() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "call one tool"}],
                    "tools": [
                        {
                            "type": "function",
                            "function": {"name": "lookup", "parameters": {}},
                        }
                    ],
                    "parallel_tool_calls": False,
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


def test_http_parallel_tool_calls_non_bool_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "parallel_tool_calls": 0,
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
            assert body["error"]["code"] == "invalid_parallel_tool_calls"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_parallel_tool_calls()
    test_http_parallel_tool_calls_false_with_tools_passthrough()
    test_http_parallel_tool_calls_non_bool_rejected()
    print("ok")
