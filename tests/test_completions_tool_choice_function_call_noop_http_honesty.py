"""Completions tool_choice/function_call none/auto/empty omit no-ops over HTTP."""

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

_TEST_AUTH_TOKEN = "completions_tool_choice_function_call_noop_token"  # noqa: S105


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


def test_http_completions_accepts_tool_choice_none_auto_empty() -> None:
    server, thread, port = _server()
    try:
        for tc in ("none", "auto", "", "  ", {}):
            status, body = _post(
                port,
                {"model": "mock-planner", "prompt": f"tc {tc!r}", "tool_choice": tc},
            )
            assert status == 200, (tc, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_function_call_none_auto_empty() -> None:
    server, thread, port = _server()
    try:
        for fc in ("none", "auto", "", "  "):
            status, body = _post(
                port,
                {"model": "mock-planner", "prompt": f"fc {fc!r}", "function_call": fc},
            )
            assert status == 200, (fc, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_still_rejects_tool_choice_required() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "required", "tool_choice": "required"},
        )
        assert status == 400, body
        assert "invalid_tools" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_still_rejects_named_function_call() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "named",
                "function_call": {"name": "lookup_item"},
            },
        )
        assert status == 400, body
        assert "invalid_tools" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_accepts_tool_choice_none_auto_empty()
    test_http_completions_accepts_function_call_none_auto_empty()
    test_http_completions_still_rejects_tool_choice_required()
    test_http_completions_still_rejects_named_function_call()
    print("ok")
