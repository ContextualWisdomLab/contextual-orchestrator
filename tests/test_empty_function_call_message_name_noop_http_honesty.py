"""Empty function_call {} and blank message name as omit no-ops over HTTP."""

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

_TEST_AUTH_TOKEN = "empty_function_call_message_name_noop_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing", "embedding"))]
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


def test_http_chat_accepts_empty_function_call_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "empty function_call object"}],
                "function_call": {},
            },
        )
        assert status == 200, body
        assert "echo" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_empty_function_call_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {"model": "mock-planner", "input": "empty function_call object", "function_call": {}},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_empty_function_call_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": "empty function_call object", "function_call": {}},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_empty_message_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "blank name", "name": ""}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_whitespace_message_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "ws name", "name": "   "}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_whitespace_suffix_as_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": "suffix ws", "suffix": "   "},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_named_function_call_without_functions() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "named function_call"}],
                "function_call": {"name": "lookup_invoice"},
            },
        )
        assert status == 400, body
        assert "invalid_functions" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_still_rejects_nonempty_suffix() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": "suffix", "suffix": ") { return 1; }"},
        )
        assert status == 400, body
        assert "invalid_suffix" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_accepts_valid_message_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "named", "name": "buyer_user"}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_empty_function_call_object()
    test_http_responses_accepts_empty_function_call_object()
    test_http_completions_accepts_empty_function_call_object()
    test_http_chat_accepts_empty_message_name()
    test_http_chat_accepts_whitespace_message_name()
    test_http_completions_accepts_whitespace_suffix_as_omit()
    test_http_chat_still_rejects_named_function_call_without_functions()
    test_http_completions_still_rejects_nonempty_suffix()
    test_http_chat_still_accepts_valid_message_name()
    print("ok")
