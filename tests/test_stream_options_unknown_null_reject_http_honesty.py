"""Unknown stream_options keys with null values fail closed over HTTP.

SDK null defaults for allowed flags (include_usage / include_obfuscation) stay
omit-equivalent. Dropping nulls *before* the allow-list check would make
``{unknown_flag: null}`` look like an empty object and silently omit — that is
dishonest. Unknown keys must raise ``invalid_stream_options`` even when null.
"""

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

_TEST_AUTH_TOKEN = "stream_options_unknown_null_reject_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
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


def test_http_chat_rejects_stream_options_unknown_null_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "unknown null"}],
                "stream_options": {"include_logprobs": None},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream_options" in blob
        assert "unknown_fields" not in blob
        assert "include_logprobs" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_allowed_stream_options_null_flags() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "allowed null"}],
                "stream_options": {
                    "include_usage": None,
                    "include_obfuscation": None,
                },
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_mixed_allowed_null_and_unknown() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "mixed"}],
                "stream_options": {
                    "include_usage": None,
                    "extra_flag": None,
                },
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream_options" in blob
        assert "extra_flag" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _function_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "lookup_balance",
            "description": "Fetch account balance",
            "parameters": {
                "type": "object",
                "properties": {"account_id": {"type": "string"}},
            },
        },
    }


def test_http_chat_tools_passthrough_rejects_stream_options_unknown_null_key() -> None:
    """tools passthrough must not bill 200 for unknown-null stream_options."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "unknown null with tools"}],
                "tools": [_function_tool()],
                "stream_options": {"include_logprobs": None},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream_options" in blob
        assert "include_logprobs" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_passthrough_rejects_include_usage_true() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "usage true with tools"}],
                "tools": [_function_tool()],
                "stream_options": {"include_usage": True},
            },
        )
        assert status == 400, body
        assert "invalid_stream_options" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_passthrough_accepts_allowed_stream_options_null_flags() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "allowed null with tools"}],
                "tools": [_function_tool()],
                "stream_options": {
                    "include_usage": None,
                    "include_obfuscation": None,
                },
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_response_format_passthrough_rejects_stream_options_unknown_null() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "unknown null with json"}],
                "response_format": {"type": "json_object"},
                "stream_options": {"extra_flag": None},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream_options" in blob
        assert "extra_flag" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_stream_options_unknown_null_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "unknown null",
                "stream_options": {"include_continuous": None},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream_options" in blob
        assert "include_continuous" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_allowed_stream_options_null_flags() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "allowed null",
                "stream_options": {"include_usage": None, "include_obfuscation": None},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_stream_options_unknown_null_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "unknown null",
                "stream_options": {"extra_flag": None},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream_options" in blob
        assert "extra_flag" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_allowed_stream_options_null_flags() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "allowed null",
                "stream_options": {"include_usage": None, "include_obfuscation": None},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_stream_options_unknown_null_key()
    test_http_chat_accepts_allowed_stream_options_null_flags()
    test_http_chat_rejects_mixed_allowed_null_and_unknown()
    test_http_chat_tools_passthrough_rejects_stream_options_unknown_null_key()
    test_http_chat_tools_passthrough_rejects_include_usage_true()
    test_http_chat_tools_passthrough_accepts_allowed_stream_options_null_flags()
    test_http_chat_response_format_passthrough_rejects_stream_options_unknown_null()
    test_http_completions_rejects_stream_options_unknown_null_key()
    test_http_completions_accepts_allowed_stream_options_null_flags()
    test_http_responses_rejects_stream_options_unknown_null_key()
    test_http_responses_accepts_allowed_stream_options_null_flags()
    print("ok")
