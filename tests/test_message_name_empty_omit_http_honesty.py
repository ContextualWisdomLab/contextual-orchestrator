"""Chat message name empty/whitespace string is omit-equivalent over HTTP."""

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
    _omit_or_validate_message_name,
    _validate_chat_message_name,
    _validate_messages,
    build_server,
)

_TEST_AUTH_TOKEN = "message_name_empty_omit_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=15) as response:
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


def test_validate_messages_omits_null_empty_and_whitespace_names() -> None:
    """Accept is not enough: rebuilt messages must drop omit-equivalent names."""
    for value in (None, "", "   ", "\t\n", "\u00a0"):
        rebuilt = _validate_messages(
            [{"role": "user", "content": "hello", "name": value}]
        )
        assert rebuilt[0]["role"] == "user"
        assert rebuilt[0]["content"] == "hello"
        assert "name" not in rebuilt[0], value


def test_omit_or_validate_message_name_pops_blank_in_place() -> None:
    message = {"role": "user", "content": "hello", "name": "   "}
    assert _omit_or_validate_message_name(message) is None
    assert "name" not in message


def test_http_chat_accepts_message_name_null_empty_and_whitespace() -> None:
    server, thread, port = _server()
    try:
        for value in (None, "", "   "):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "hello", "name": value}],
                },
            )
            assert status == 200, (value, body)
            rebuilt = _validate_messages(
                [{"role": "user", "content": "hello", "name": value}]
            )
            assert "name" not in rebuilt[0], value
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_message_name_non_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "hello", "name": 123}],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message_name" in blob
        assert "unknown_fields" not in blob
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
                "messages": [{"role": "user", "content": "hello", "name": "n" * 65}],
            },
        )
        assert status == 400, body
        assert "invalid_message_name" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_validate_chat_message_name_fail_closes_before_tools_passthrough() -> None:
    """Tools path must reject non-string / over-long / bad-charset names."""
    for value in (123, "n" * 65, "bad name!", "\u200b"):
        body = {
            "messages": [{"role": "user", "content": "hello", "name": value}],
            "tools": [{"type": "function", "function": {"name": "lookup"}}],
        }
        try:
            _validate_chat_message_name(body)
        except RequestError as exc:
            assert exc.code == "invalid_message_name", (value, exc)
        else:
            raise AssertionError(f"expected invalid_message_name for {value!r}")


def test_validate_chat_message_name_pops_blank_on_tools_body() -> None:
    body = {
        "messages": [{"role": "user", "content": "hello", "name": ""}],
        "tools": [{"type": "function", "function": {"name": "lookup"}}],
    }
    _validate_chat_message_name(body)
    assert "name" not in body["messages"][0]


if __name__ == "__main__":
    test_validate_messages_omits_null_empty_and_whitespace_names()
    test_omit_or_validate_message_name_pops_blank_in_place()
    test_http_chat_accepts_message_name_null_empty_and_whitespace()
    test_http_chat_rejects_message_name_non_string()
    test_http_chat_rejects_message_name_too_long()
    test_validate_chat_message_name_fail_closes_before_tools_passthrough()
    test_validate_chat_message_name_pops_blank_on_tools_body()
    print("ok")
