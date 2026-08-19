"""tool type / message role casefold honesty over HTTP (form/JS SDK parity)."""

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

_TEST_AUTH_TOKEN = "tool_type_role_casefold_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=10) as response:
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


def test_http_chat_accepts_message_role_casefold() -> None:
    server, thread, port = _server()
    try:
        for role in ("user", "User", "USER", " user ", "UsEr"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": role, "content": f"role {role!r}"}],
                },
            )
            assert status == 200, (role, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_developer_role_casefold_as_system() -> None:
    server, thread, port = _server()
    try:
        for role in ("developer", "Developer", " DEVELOPER "):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [
                        {"role": role, "content": "dev plane"},
                        {"role": "user", "content": "hi"},
                    ],
                },
            )
            assert status == 200, (role, body)
            assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_function_role_casefold() -> None:
    server, thread, port = _server()
    try:
        for role in ("function", "Function", " FUNCTION "):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": role, "content": "legacy fn"}],
                },
            )
            assert status == 400, (role, body)
            assert "invalid_message_role" in json.dumps(body)
            assert "tool" in json.dumps(body).lower()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_type_casefold() -> None:
    server, thread, port = _server()
    try:
        for tool_type in ("function", "Function", "FUNCTION", " function "):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"type {tool_type!r}"}],
                    "tools": [
                        {
                            "type": tool_type,
                            "function": {
                                "name": "lookup",
                                "parameters": {"type": "object"},
                            },
                        }
                    ],
                },
            )
            assert status == 200, (tool_type, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_choice_type_casefold() -> None:
    server, thread, port = _server()
    try:
        for choice_type in ("function", "Function", " FUNCTION "):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"choice {choice_type!r}"}],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "parameters": {"type": "object"},
                            },
                        }
                    ],
                    "tool_choice": {
                        "type": choice_type,
                        "function": {"name": "lookup"},
                    },
                },
            )
            assert status == 200, (choice_type, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_assistant_tool_calls_type_casefold() -> None:
    server, thread, port = _server()
    try:
        for call_type in ("function", "Function", " FUNCTION "):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [
                        {"role": "user", "content": "prior"},
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": call_type,
                                    "function": {
                                        "name": "lookup",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": "call_1",
                            "content": "ok",
                        },
                    ],
                },
            )
            assert status == 200, (call_type, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_unknown_tool_type() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bad type"}],
                "tools": [
                    {
                        "type": "custom",
                        "function": {
                            "name": "lookup",
                            "parameters": {"type": "object"},
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


def test_http_responses_accepts_tool_type_casefold() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "tool type Function",
                "tools": [
                    {
                        "type": "Function",
                        "function": {
                            "name": "lookup",
                            "parameters": {"type": "object"},
                        },
                    }
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)
