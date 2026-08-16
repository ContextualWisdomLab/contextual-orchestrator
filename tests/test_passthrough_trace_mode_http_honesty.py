"""Tools passthrough must type-check include_orchestration_trace and mode.

Those knobs are unused on the single-agent proxy, but a non-boolean
``include_orchestration_trace`` or an unknown ``mode`` used to bill a
completion (JSON or SSE) instead of the same named 400 the orchestration
path returns. Hoist the checks before ``proxy_completion`` /
``proxy_completion_stream``.

OpenAI. (2024). *Create chat completion*. OpenAI API reference.
https://platform.openai.com/docs/api-reference/chat/create
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

_TEST_AUTH_TOKEN = "passthrough_trace_mode_http_honesty_token"  # noqa: S105

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
            raw = response.read().decode("utf-8")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, {
                    "_raw": raw,
                    "_content_type": response.headers.get("content-type", ""),
                }
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


def _tools_payload(**extra: object) -> dict:
    payload = {
        "model": "mock-planner",
        "messages": [{"role": "user", "content": "lookup invoice 4412"}],
        "tools": _LOOKUP_TOOLS,
    }
    payload.update(extra)
    return payload


def test_http_tools_rejects_include_orchestration_trace_non_boolean() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _tools_payload(include_orchestration_trace="yes"),
        )
        assert status == 400, body
        assert "invalid_include_orchestration_trace" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_rejects_include_orchestration_trace_non_boolean_stream() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _tools_payload(include_orchestration_trace="yes", stream=True),
        )
        assert status == 400, body
        assert "invalid_include_orchestration_trace" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_rejects_include_orchestration_trace_true() -> None:
    """Passthrough has no TRINITY plane — true must 400, not bill."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _tools_payload(include_orchestration_trace=True),
        )
        assert status == 400, body
        assert "invalid_include_orchestration_trace" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_accepts_include_orchestration_trace_false_and_null() -> None:
    server, thread, port = _server()
    try:
        for value in (False, None):
            status, body = _post(
                port,
                _tools_payload(include_orchestration_trace=value),
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_rejects_invalid_mode() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_payload(mode="cascade"))
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_rejects_mode_non_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_payload(orchestration=1))
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_accepts_valid_mode_on_passthrough() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _tools_payload(mode="route"))
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_tools_rejects_include_orchestration_trace_non_boolean()
    test_http_tools_rejects_include_orchestration_trace_non_boolean_stream()
    test_http_tools_rejects_include_orchestration_trace_true()
    test_http_tools_accepts_include_orchestration_trace_false_and_null()
    test_http_tools_rejects_invalid_mode()
    test_http_tools_rejects_mode_non_string()
    test_http_tools_accepts_valid_mode_on_passthrough()
    print("ok")
