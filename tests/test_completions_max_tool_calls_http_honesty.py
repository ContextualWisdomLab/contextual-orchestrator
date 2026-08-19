"""Legacy Completions max_tool_calls honesty: null/empty omit; else fail-closed."""

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

_TEST_AUTH_TOKEN = "completions_max_tool_calls_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/completions",
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


def test_http_completions_accepts_max_tool_calls_null_and_empty_string() -> None:
    server, thread, port = _server()
    try:
        for value in (None, "", "   "):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "prompt": "hello",
                    "max_tool_calls": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_max_tool_calls_nonzero() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "hello",
                "max_tool_calls": 3,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_max_tool_calls" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_max_tool_calls_one() -> None:
    """Even max_tool_calls=1 is unsupported — no tool loop on Completions."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "hello",
                "max_tool_calls": 1,
            },
        )
        assert status == 400, body
        assert "invalid_max_tool_calls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_max_tool_calls_zero_omit() -> None:
    """Integer 0 is omit-equivalent (no tool-call rounds requested)."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "hello",
                "max_tool_calls": 0,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_max_tool_calls_bool() -> None:
    """bool is not an integer tool-round count — fail closed."""
    server, thread, port = _server()
    try:
        for value in (False, True):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "prompt": "hello",
                    "max_tool_calls": value,
                },
            )
            assert status == 400, (value, body)
            assert "invalid_max_tool_calls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_accepts_max_tool_calls_null_and_empty_string()
    test_http_completions_rejects_max_tool_calls_nonzero()
    test_http_completions_rejects_max_tool_calls_one()
    test_http_completions_accepts_max_tool_calls_zero_omit()
    test_http_completions_rejects_max_tool_calls_bool()
    print("ok")
