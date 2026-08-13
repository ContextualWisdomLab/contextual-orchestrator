"""Responses parallel_tool_calls honesty over HTTP (fail-closed)."""

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

_TEST_AUTH_TOKEN = "responses_parallel_tool_calls_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/responses",
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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_responses_accepts_omitted_parallel_tool_calls() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "mock-planner", "input": "hello ptc omit"})
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_boolean_parallel_tool_calls() -> None:
    server, thread, port = _server()
    try:
        for value in (True, False):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "input": f"hello ptc {value}",
                    "parallel_tool_calls": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_non_boolean_parallel_tool_calls() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello ptc bad",
                "parallel_tool_calls": "yes",
            },
        )
        assert status == 400, body
        assert "invalid_parallel_tool_calls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_integer_parallel_tool_calls() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello ptc int",
                "parallel_tool_calls": 1,
            },
        )
        assert status == 400, body
        assert "invalid_parallel_tool_calls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_accepts_omitted_parallel_tool_calls()
    test_http_responses_accepts_boolean_parallel_tool_calls()
    test_http_responses_rejects_non_boolean_parallel_tool_calls()
    test_http_responses_rejects_integer_parallel_tool_calls()
    print("ok")
