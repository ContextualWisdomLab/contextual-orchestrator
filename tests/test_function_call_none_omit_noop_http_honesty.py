"""function_call "none" as omit no-op honesty over HTTP (parity with tool_choice none)."""

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

_TEST_AUTH_TOKEN = "function_call_none_omit_noop_http_honesty_token"  # noqa: S105


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
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_function_call_none_as_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "fn none"}],
                "function_call": "none",
            },
        )
        assert status == 200, body
        # Must stay on multi-agent orchestration path (not forced passthrough).
        assert body.get("object") == "chat.completion", body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_function_call_none_with_empty_functions() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "fn none empty"}],
                "functions": [],
                "function_call": "none",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_function_call_none_as_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "fn none responses",
                "function_call": "none",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_function_call_none_and_tool_choice_none() -> None:
    server, thread, port = _server()
    try:
        for extra in (
            {"function_call": "none"},
            {"tool_choice": "none"},
            {"function_call": "none", "tool_choice": "none", "functions": [], "tools": []},
        ):
            status, body = _post(
                port,
                "/v1/completions",
                {"model": "mock-planner", "prompt": "legacy none", **extra},
            )
            assert status == 200, (extra, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_function_call_auto() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "fn auto"}],
                "function_call": "auto",
            },
        )
        assert status == 400, body
        assert "invalid_functions" in json.dumps(body)
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
                "function_call": "none",
            },
        )
        assert status == 400, body
        assert "invalid_functions" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_function_call_none_as_omit()
    test_http_chat_accepts_function_call_none_with_empty_functions()
    test_http_responses_accepts_function_call_none_as_omit()
    test_http_completions_accepts_function_call_none_and_tool_choice_none()
    test_http_chat_still_rejects_function_call_auto()
    test_http_chat_still_rejects_nonempty_functions()
    print("ok")
