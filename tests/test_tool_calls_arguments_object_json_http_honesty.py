"""tool_calls.function.arguments object/array → JSON text over HTTP."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "tool_calls_arguments_object_json_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


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


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_tool_calls_arguments_object_and_array() -> None:
    server, thread, port = _server()
    try:
        for args in ({"q": "x", "n": 2}, [], [{"k": 1}], {"nested": {"a": True}}):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [
                        {"role": "user", "content": f"args {args!r}"},
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "lookup_item", "arguments": args},
                                }
                            ],
                        },
                    ],
                },
            )
            assert status == 200, (args, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_tool_calls_arguments_number_bool() -> None:
    server, thread, port = _server()
    try:
        for args in (3, True, 1.5):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [
                        {"role": "user", "content": f"bad {args!r}"},
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "lookup_item", "arguments": args},
                                }
                            ],
                        },
                    ],
                },
            )
            assert status == 400, (args, body)
            assert "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_tool_calls_arguments_object_and_array()
    test_http_chat_still_rejects_tool_calls_arguments_number_bool()
    print("ok")
