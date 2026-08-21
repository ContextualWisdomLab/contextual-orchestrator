"""tool_choice and function_call padded/casefold honesty over HTTP."""

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

_TEST_AUTH_TOKEN = "tool_choice_function_call_casefold_http_honesty_token"  # noqa: S105


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


def test_http_chat_accepts_function_call_none_auto_padded_casefold() -> None:
    server, thread, port = _server()
    try:
        for value in ("none", "auto", " NONE ", " Auto ", "AUTO"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "fc"}],
                    "function_call": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_choice_required_padded_casefold_with_tools() -> None:
    server, thread, port = _server()
    try:
        for value in ("required", " REQUIRED ", "Required"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "tc"}],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "parameters": {"type": "object", "properties": {}},
                            },
                        }
                    ],
                    "tool_choice": value,
                },
            )
            assert status == 422, (value, body)
            assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_choice_none_auto_padded_casefold() -> None:
    server, thread, port = _server()
    try:
        for value in ("none", "auto", " NONE ", " AUTO "):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "tc noop"}],
                    "tool_choice": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_function_call_none_padded_casefold() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "fc",
                "function_call": " NONE ",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_function_call_none_auto_padded_casefold()
    test_http_chat_rejects_tool_choice_required_padded_casefold_with_tools()
    test_http_chat_accepts_tool_choice_none_auto_padded_casefold()
    test_http_completions_accepts_function_call_none_padded_casefold()
    print("ok")
