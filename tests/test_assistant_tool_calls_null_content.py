"""Assistant tool_calls with null content for multi-turn tool history."""

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
    _validate_assistant_tool_calls,
    _validate_messages,
    build_server,
)

_TEST_AUTH_TOKEN = "asst_tc_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_tool_calls_and_null_content() -> None:
    calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "lookup", "arguments": "{}"},
        }
    ]
    assert _validate_assistant_tool_calls(calls) == calls
    msgs = _validate_messages(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": None, "tool_calls": calls},
            {"role": "tool", "content": "ok", "tool_call_id": "call_1"},
        ]
    )
    assert msgs[1]["content"] == ""
    assert msgs[1]["tool_calls"] == calls
    try:
        _validate_assistant_tool_calls([{"id": "", "type": "function", "function": {"name": "x"}}])
        raise AssertionError("expected invalid_tool_calls")
    except RequestError as exc:
        assert exc.code == "invalid_tool_calls"


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


def test_http_chat_accepts_null_assistant_content_with_tool_calls() -> None:
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
                "messages": [
                    {"role": "user", "content": "lookup weather"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city":"Seoul"}',
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call_abc",
                        "content": '{"temp": 22}',
                    },
                ],
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_bad_tool_calls() -> None:
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
                "messages": [
                    {"role": "user", "content": "hi"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": "x", "type": "function", "function": {}}],
                    },
                ],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_tool_calls"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_tool_calls_and_null_content()
    test_http_chat_accepts_null_assistant_content_with_tool_calls()
    test_http_chat_rejects_bad_tool_calls()
    print("ok")
