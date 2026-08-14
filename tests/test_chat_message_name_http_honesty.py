"""Chat message participant name honesty over HTTP (OpenAI optional name field)."""

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

_TEST_AUTH_TOKEN = "chat_message_name_http_honesty_token"  # noqa: S105


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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_user_message_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "hello", "name": "buyer_alpha"},
                ],
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_system_and_assistant_names() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "system", "content": "Be concise.", "name": "policy_bot"},
                    {"role": "user", "content": "hi", "name": "user_1"},
                    {"role": "assistant", "content": "hello", "name": "assistant_a"},
                    {"role": "user", "content": "continue"},
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_empty_message_name_as_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "hi", "name": "   "}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_message_name_too_long() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "hi", "name": "a" * 65}],
            },
        )
        assert status == 400, body
        assert "invalid_message_name" in json.dumps(body)
        assert "64" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_message_name_bad_charset() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "hi", "name": "bad name!"}],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message_name" in blob
        assert "a-zA-Z0-9" in blob or "match" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_name_on_tool_message() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "run tool"},
                    {
                        "role": "tool",
                        "content": "result",
                        "tool_call_id": "call_1",
                        "name": "should_not_be_here",
                    },
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message_name" in blob
        assert "tool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_name_with_underscore_hyphen() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "ping", "name": "Buyer-Agent_01"},
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_user_message_name()
    test_http_chat_accepts_system_and_assistant_names()
    test_http_chat_accepts_empty_message_name_as_omit()
    test_http_chat_rejects_message_name_too_long()
    test_http_chat_rejects_message_name_bad_charset()
    test_http_chat_rejects_name_on_tool_message()
    test_http_chat_accepts_name_with_underscore_hyphen()
    print("ok")
