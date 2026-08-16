"""Tools-path chat message name honesty: omit blanks, fail-closed otherwise."""

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

_TEST_AUTH_TOKEN = "message_name_tools_passthrough_http_honesty_token"  # noqa: S105

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_balance",
            "description": "Fetch account balance",
            "parameters": {"type": "object", "properties": {"account_id": {"type": "string"}}},
        },
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


def test_http_tools_path_accepts_blank_message_name_as_omit() -> None:
    """SDK blank participant names must not 400 on the tools passthrough path."""
    server, thread, port = _server()
    try:
        for value in (None, "", "   ", "\t\n"):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "lookup", "name": value}],
                    "tools": _TOOLS,
                },
            )
            assert status == 200, (value, body)
            assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_path_rejects_non_string_message_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "lookup", "name": 123}],
                "tools": _TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message_name" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_path_rejects_overlong_and_bad_charset_names() -> None:
    server, thread, port = _server()
    try:
        for value in ("n" * 65, "bad name!", "\u200b"):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "lookup", "name": value}],
                    "tools": _TOOLS,
                },
            )
            assert status == 400, (value, body)
            assert "invalid_message_name" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_path_rejects_nonblank_name_on_tool_role() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "lookup"},
                    {
                        "role": "tool",
                        "content": "ok",
                        "tool_call_id": "call_1",
                        "name": "lookup_balance",
                    },
                ],
                "tools": _TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message_name" in blob
        assert "tool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_path_omits_blank_name_on_tool_role() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "lookup"},
                    {
                        "role": "tool",
                        "content": "ok",
                        "tool_call_id": "call_1",
                        "name": "",
                    },
                ],
                "tools": _TOOLS,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_tools_path_accepts_blank_message_name_as_omit()
    test_http_tools_path_rejects_non_string_message_name()
    test_http_tools_path_rejects_overlong_and_bad_charset_names()
    test_http_tools_path_rejects_nonblank_name_on_tool_role()
    test_http_tools_path_omits_blank_name_on_tool_role()
    print("ok")
