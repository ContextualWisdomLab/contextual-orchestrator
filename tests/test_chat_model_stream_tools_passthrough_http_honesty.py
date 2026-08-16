"""Tools passthrough must fail-closed on model and stream.

``_validate_completions_model`` / ``_require_pool_model`` and chat ``stream``
honesty run after the tools/response_format early-return. SDK tool-calling
bodies that omit ``model`` or set ``stream=true`` must not bill a JSON
completion or silent-select a worker. Named ``invalid_model`` /
``invalid_stream`` must match the orchestration path.
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

_TEST_AUTH_TOKEN = "chat_model_stream_tools_passthrough_token"  # noqa: S105

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
    """OpenAI SDKs that omit model must not silent-select a pool worker."""
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
        blob = json.dumps(body)
        assert "invalid_model" in blob
        assert "required" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_model_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "not-in-the-agent-pool",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_model" in blob
        assert "not available" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_stream_true_with_tools() -> None:
    """SSE passthrough is a follow-up; do not return a JSON 200 for stream=true."""
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
        assert "stream=false" in blob or "omit stream" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_omitted_model_with_response_format() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "messages": [{"role": "user", "content": "return JSON"}],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_model" in blob
        assert "required" in blob
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
                "messages": [{"role": "user", "content": "return JSON"}],
                "response_format": {"type": "json_object"},
                "stream": True,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_named_model_stream_false_with_tools() -> None:
    """Honest SDK body: pool model + stream omitted/false still proxies."""
    server, thread, port = _server()
    try:
        for stream in (None, False):
            payload = {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
            }
            if stream is not None:
                payload["stream"] = stream
            status, body = _post(port, payload)
            assert status == 200, (stream, body)
            assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_omitted_model_with_tools()
    test_http_chat_rejects_unknown_model_with_tools()
    test_http_chat_rejects_stream_true_with_tools()
    test_http_chat_rejects_omitted_model_with_response_format()
    test_http_chat_rejects_stream_true_with_response_format()
    test_http_chat_accepts_named_model_stream_false_with_tools()
    print("ok")
