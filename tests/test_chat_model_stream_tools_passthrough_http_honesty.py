"""Chat tools passthrough must require a pool model and fail-closed on stream=true.

Buyer SDKs that send non-empty ``tools`` take the single-agent early-return.
That path previously skipped ``_validate_completions_model`` / ``_require_pool_model``
and forced ``stream=false`` upstream, so omitted model silent-selected a worker
and ``stream: true`` returned a JSON 200 instead of SSE or a named reject.
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

_TEST_AUTH_TOKEN = "chat_model_stream_tools_passthrough_http_honesty_token"  # noqa: S105

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


def test_http_chat_rejects_omitted_model_with_tools() -> None:
    """Omitted model must not silent-select a worker on the tools path."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "messages": [{"role": "user", "content": "lookup the invoice balance"}],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_model" in blob
        assert "required" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_pool_model_with_tools() -> None:
    """A named model outside the agent pool must fail closed on tools passthrough."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "lookup the invoice balance"}],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_model" in blob
        assert "gpt-4o-mini" in blob
        assert "agent pool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_stream_true_with_tools() -> None:
    """Tools passthrough has no SSE plane — stream=true must not return JSON 200."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "stream the lookup"}],
                "tools": _LOOKUP_TOOLS,
                "stream": True,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream" in blob
        assert "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_named_pool_model_and_stream_false_with_tools() -> None:
    """Honest tools passthrough: named pool model + non-stream still 200."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "lookup the invoice balance"}],
                "tools": _LOOKUP_TOOLS,
                "stream": False,
            },
        )
        assert status == 200, body
        assert "choices" in body
        echo = body.get("echo") or {}
        assert echo.get("tools") == _LOOKUP_TOOLS
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_omitted_model_with_tools()
    test_http_chat_rejects_unknown_pool_model_with_tools()
    test_http_chat_rejects_stream_true_with_tools()
    test_http_chat_accepts_named_pool_model_and_stream_false_with_tools()
    print("ok")
