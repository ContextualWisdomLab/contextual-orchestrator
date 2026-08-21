"""JS-style bool 0/1 coerce + digit-string seed honesty over HTTP."""

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

_TEST_AUTH_TOKEN = "bool_01_seed_str_http_honesty_token"  # noqa: S105


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


def test_http_chat_accepts_store_zero_as_false() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "store0"}],
                "store": 0,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_store_one_as_true() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "store1"}],
                "store": 1,
            },
        )
        assert status == 400, body
        assert "invalid_store" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_stream_zero_as_false() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "stream0"}],
                "stream": 0,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_parallel_tool_calls_zero() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "ptc0"}],
                "parallel_tool_calls": 0,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_parallel_tool_calls_one_requires_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "ptc1"}],
                "parallel_tool_calls": 1,
            },
        )
        assert status == 400, body
        assert "invalid_parallel_tool_calls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_unapplied_seed_digit_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {"model": "mock-planner", "input": "seed str", "seed": "42"},
        )
        assert status == 422, body
        assert "unsupported_responses_orchestration_controls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_seed_digit_string_as_unsupported() -> None:
    """Digit string coerces to int then fails closed (seed not applied)."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": "seed", "seed": "7"},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_seed" in blob
        assert "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_store_zero_as_false()
    test_http_chat_rejects_store_one_as_true()
    test_http_chat_accepts_stream_zero_as_false()
    test_http_chat_accepts_parallel_tool_calls_zero()
    test_http_chat_parallel_tool_calls_one_requires_tools()
    test_http_responses_rejects_unapplied_seed_digit_string()
    test_http_completions_rejects_seed_digit_string_as_unsupported()
    print("ok")
