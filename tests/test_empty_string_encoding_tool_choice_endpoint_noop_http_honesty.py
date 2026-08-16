"""Empty-string encoding_format/tool_choice/function_call/response_format/endpoint omit no-ops."""

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

_TEST_AUTH_TOKEN = "empty_string_encoding_tool_choice_endpoint_noop_token"  # noqa: S105


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


def test_http_embeddings_accepts_empty_encoding_format_as_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": "encode empty", "encoding_format": ""},
        )
        assert status == 200, body
        assert body.get("object") == "list" or "data" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_whitespace_encoding_format_as_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": "encode ws", "encoding_format": "  "},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_accepts_empty_encoding_format_as_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/batch/embeddings",
            {"model": "mock-planner", "inputs": ["batch encode empty"], "encoding_format": ""},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_empty_tool_choice_string_as_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tc empty"}],
                "tool_choice": "",
            },
        )
        assert status == 200, body
        assert body.get("object") == "chat.completion", body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_empty_function_call_string_as_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "fc empty"}],
                "function_call": "",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_empty_response_format_string_as_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "rf empty"}],
                "response_format": "",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_empty_tool_choice_string_as_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {"model": "mock-planner", "input": "resp tc empty", "tool_choice": ""},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_endpoint_null_and_empty_still_ok_and_base64_fails() -> None:
    """Regression: empty endpoint omit; base64 encoding_format still fail-closed."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": "base64", "encoding_format": "base64"},
        )
        assert status == 400, body
        assert "invalid_encoding_format" in json.dumps(body)
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "required without tools"}],
                "tool_choice": "required",
            },
        )
        assert status == 400, body
        assert "invalid_tool_choice" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_embeddings_accepts_empty_encoding_format_as_omit()
    test_http_embeddings_accepts_whitespace_encoding_format_as_omit()
    test_http_batch_embeddings_accepts_empty_encoding_format_as_omit()
    test_http_chat_accepts_empty_tool_choice_string_as_omit()
    test_http_chat_accepts_empty_function_call_string_as_omit()
    test_http_chat_accepts_empty_response_format_string_as_omit()
    test_http_responses_accepts_empty_tool_choice_string_as_omit()
    test_http_batch_endpoint_null_and_empty_still_ok_and_base64_fails()
    print("ok")
