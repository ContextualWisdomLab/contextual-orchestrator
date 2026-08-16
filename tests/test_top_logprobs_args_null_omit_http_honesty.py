"""top_logprobs empty-string omit + tool_calls function.arguments null omit over HTTP."""

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
    SecurityConfig,
    build_server,
    _validate_chat_assistant_tool_calls,
)

_TEST_AUTH_TOKEN = "top_logprobs_args_null_omit_http_honesty_token"  # noqa: S105


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


def test_http_chat_accepts_top_logprobs_null_empty_zero() -> None:
    server, thread, port = _server()
    try:
        for value in (None, "", "   ", 0):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "tlp omit"}],
                    "top_logprobs": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_top_logprobs_nonzero() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tlp 5"}],
                "top_logprobs": 5,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_top_logprobs" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_top_logprobs_empty_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "tlp empty",
                "top_logprobs": "",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_calls_arguments_null() -> None:
    """SDK optional null arguments is omit-equivalent to empty JSON-text string."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": None},
                            }
                        ],
                    },
                    {"role": "user", "content": "continue"},
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _function_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Lookup a record",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_validate_persists_null_arguments_as_empty_json_text() -> None:
    """Null arguments must become a string on the body, not a local-only coerce."""
    body = {
        "messages": [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": None},
                    }
                ],
            }
        ]
    }
    _validate_chat_assistant_tool_calls(body)
    stored = body["messages"][0]["tool_calls"][0]["function"]["arguments"]
    assert stored == ""
    assert isinstance(stored, str)


def test_http_chat_tools_rejects_top_logprobs_nonzero() -> None:
    """tools passthrough must not accept applied top_logprobs (buyer honesty)."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tlp tools 5"}],
                "tools": _function_tools(),
                "top_logprobs": 5,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_top_logprobs" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_top_logprobs_empty_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tlp tools empty"}],
                "tools": _function_tools(),
                "top_logprobs": "",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_arguments_null() -> None:
    """tools + history arguments:null must accept after persist-to-empty-string."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": None},
                            }
                        ],
                    },
                    {"role": "user", "content": "continue"},
                ],
                "tools": _function_tools(),
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_top_logprobs_empty_string() -> None:
    """Responses empty/whitespace top_logprobs is omit (chat/Completions parity)."""
    server, thread, port = _server()
    try:
        for value in (None, "", "   "):
            status, body = _post(
                port,
                "/v1/responses",
                {
                    "model": "mock-planner",
                    "input": "tlp omit",
                    "top_logprobs": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_calls_arguments_non_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": {"x": 1}},
                            }
                        ],
                    },
                    {"role": "user", "content": "continue"},
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "arguments" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_top_logprobs_null_empty_zero()
    test_http_chat_rejects_top_logprobs_nonzero()
    test_http_completions_accepts_top_logprobs_empty_string()
    test_http_chat_accepts_tool_calls_arguments_null()
    test_validate_persists_null_arguments_as_empty_json_text()
    test_http_chat_tools_rejects_top_logprobs_nonzero()
    test_http_chat_tools_accepts_top_logprobs_empty_string()
    test_http_chat_tools_accepts_arguments_null()
    test_http_responses_accepts_top_logprobs_empty_string()
    test_http_chat_rejects_tool_calls_arguments_non_string()
    print("ok")
