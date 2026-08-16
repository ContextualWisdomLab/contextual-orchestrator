"""Tools/response_format passthrough must fail-closed on stream, model, and sampling range.

``_validate_messages`` is skipped when ``tools`` / ``response_format`` force
single-agent passthrough. Request-level stream, required ``model``,
``stream_options``, and temperature/top_p range were also skipped, so an
OpenAI SDK tool-calling body could receive a billed JSON completion when it
asked for SSE, or a silent pool pick when it omitted ``model``.
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

_TEST_AUTH_TOKEN = "passthrough_stream_model_http_honesty_token"  # noqa: S105

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


def _post(port: int, payload: dict) -> tuple[int, dict | str]:
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
            raw = response.read().decode("utf-8")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_rejects_stream_true_with_tools() -> None:
    """SDK tool-calling streams must not receive a silent JSON completion."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "stream": True,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream" in blob
        assert "tools" in blob or "response_format" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_stream_true_with_response_format() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "return json"}],
                "response_format": {"type": "json_object"},
                "stream": True,
            },
        )
        assert status == 400, body
        assert "invalid_stream" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_missing_model_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_model" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_model_with_tools() -> None:
    """Named model must be in the pool; silent rewrite is a commercial honesty failure."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_model" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_stream_options_usage_true_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "stream_options": {"include_usage": True},
            },
        )
        assert status == 400, body
        assert "invalid_stream_options" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_top_p_out_of_range_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "top_p": 2,
            },
        )
        assert status == 400, body
        assert "invalid_top_p" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_temperature_out_of_range_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "temperature": 99,
            },
        )
        assert status == 400, body
        assert "invalid_temperature" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_in_range_temperature_with_tools() -> None:
    """Valid sampling knobs stay forwarded on passthrough after the range check."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "temperature": 0.2,
            },
        )
        assert status == 200, body
        assert isinstance(body, dict)
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_stream_null_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "stream": None,
            },
        )
        assert status == 200, body
        assert isinstance(body, dict)
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_route_stream_without_tools_still_sse() -> None:
    """Plain chat streaming must keep working; only passthrough triggers fail closed."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "one sentence"}],
                "stream": True,
            },
        )
        assert status == 200, body
        blob = body if isinstance(body, str) else json.dumps(body)
        assert "chat.completion.chunk" in blob or "data:" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_stream_true_with_tools()
    test_http_chat_rejects_stream_true_with_response_format()
    test_http_chat_rejects_missing_model_with_tools()
    test_http_chat_rejects_unknown_model_with_tools()
    test_http_chat_rejects_stream_options_usage_true_with_tools()
    test_http_chat_rejects_top_p_out_of_range_with_tools()
    test_http_chat_rejects_temperature_out_of_range_with_tools()
    test_http_chat_accepts_in_range_temperature_with_tools()
    test_http_chat_accepts_stream_null_with_tools()
    test_http_chat_route_stream_without_tools_still_sse()
    print("ok")
