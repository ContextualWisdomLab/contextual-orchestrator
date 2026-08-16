"""Empty or malformed ``messages`` must fail closed before tools passthrough.

``_validate_messages`` runs after the tools / response_format early-return.
SDK tool-calling bodies that omit ``messages``, send ``[]``, ``null``, a
non-list, or a non-object entry were billed as ``chat.completion`` (or 500
on ``str.get``). Buyers must get the same ``invalid_message`` as the
orchestration path — never a completion with no prompt.
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

_TEST_AUTH_TOKEN = "chat_messages_array_tools_passthrough_http_honesty_token"  # noqa: S105

_LOOKUP_TOOLS = [
    {
        "type": "function",
        "function": {"name": "lookup_balance", "parameters": {"type": "object"}},
    }
]


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


def test_http_chat_rejects_empty_messages_with_tools() -> None:
    """A billed completion with no prompt is not an honest tool-calling response."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_omitted_messages_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_null_messages_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": None,
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_list_messages_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": "look up the invoice",
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_object_message_with_tools() -> None:
    """A string entry must be 400, not 500 from ``str.get`` in the proxy."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": ["look up the invoice"],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message" in json.dumps(body)
        assert "internal_error" not in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_role_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "narrator", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_string_content_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": 42}],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_empty_messages_with_response_format() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 400, body
        assert "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_max_tokens_negative_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "max_tokens": -1,
            },
        )
        assert status == 400, body
        assert "invalid_max_tokens" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_attribution_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "attribution": {"not_a_dimension": "acct-1"},
            },
        )
        assert status == 400, body
        assert "invalid_attribution" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_routing_key_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "routing": {"channel": "batch", "region": "us-east"},
            },
        )
        assert status == 400, body
        assert "invalid_routing" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_null_stream_options_with_tools() -> None:
    """Unknown stream_options keys stay fail-closed even when the value is null."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "stream_options": {"include_continuous": None},
            },
        )
        assert status == 400, body
        assert "invalid_stream_options" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_empty_messages_with_tools()
    test_http_chat_rejects_omitted_messages_with_tools()
    test_http_chat_rejects_null_messages_with_tools()
    test_http_chat_rejects_non_list_messages_with_tools()
    test_http_chat_rejects_non_object_message_with_tools()
    test_http_chat_rejects_unknown_role_with_tools()
    test_http_chat_rejects_non_string_content_with_tools()
    test_http_chat_rejects_empty_messages_with_response_format()
    test_http_chat_rejects_max_tokens_negative_with_tools()
    test_http_chat_rejects_unknown_attribution_with_tools()
    test_http_chat_rejects_unknown_routing_key_with_tools()
    test_http_chat_rejects_unknown_null_stream_options_with_tools()
    print("ok")
