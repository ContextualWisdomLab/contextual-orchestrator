"""functions/function_call null/empty and max_tool_calls null as omit no-ops over HTTP."""

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

_TEST_AUTH_TOKEN = "functions_null_max_tool_calls_null_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing", "embedding"))]
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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_null_and_empty_functions() -> None:
    server, thread, port = _server()
    try:
        for payload_extra in (
            {"functions": None},
            {"functions": []},
            {"function_call": None},
            {"functions": None, "function_call": None},
        ):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "fn null"}],
                    **payload_extra,
                },
            )
            assert status == 200, (payload_extra, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_nonempty_functions() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "fn nonempty"}],
                "functions": [{"name": "lookup", "parameters": {"type": "object"}}],
            },
        )
        assert status == 400, body
        assert "invalid_functions" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_null_max_tool_calls_and_functions() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "max tool null",
                "max_tool_calls": None,
                "functions": [],
                "function_call": None,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_still_rejects_max_tool_calls() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "max tool 3",
                "max_tool_calls": 3,
            },
        )
        assert status == 400, body
        assert "invalid_max_tool_calls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_null_and_empty_functions()
    test_http_chat_still_rejects_nonempty_functions()
    test_http_responses_accepts_null_max_tool_calls_and_functions()
    test_http_responses_still_rejects_max_tool_calls()
    print("ok")
