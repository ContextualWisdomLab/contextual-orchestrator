"""tool.function description/parameters null are omit-equivalent over HTTP."""

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

_TEST_AUTH_TOKEN = "tool_description_parameters_null_noop_http_honesty_token"  # noqa: S105


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


def test_http_chat_accepts_tool_description_null() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "desc null"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": None,
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_parameters_null() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "params null"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": None,
                        },
                    }
                ],
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_description_and_parameters_null() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "both null"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": None,
                            "parameters": None,
                            "strict": None,
                        },
                    }
                ],
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_description_non_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "desc bad"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": 123,
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_tools" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_tool_parameters_non_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "params bad"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": "not-an-object",
                        },
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_tools" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_tool_description_null()
    test_http_chat_accepts_tool_parameters_null()
    test_http_chat_accepts_tool_description_and_parameters_null()
    test_http_chat_rejects_tool_description_non_string()
    test_http_chat_rejects_tool_parameters_non_object()
    print("ok")
