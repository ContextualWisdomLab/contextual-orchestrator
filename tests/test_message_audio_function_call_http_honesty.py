"""Message audio/function_call null-empty omit and non-empty fail-closed honesty."""

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

_TEST_AUTH_TOKEN = "message_audio_function_call_http_honesty_token"  # noqa: S105


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


def test_http_chat_accepts_message_audio_null_and_empty() -> None:
    server, thread, port = _server()
    try:
        for audio in (None, {}):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [
                        {"role": "assistant", "content": "prior", "audio": audio},
                        {"role": "user", "content": "continue"},
                    ],
                },
            )
            assert status == 200, (audio, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_nonempty_message_audio() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "assistant",
                        "content": "prior",
                        "audio": {"id": "audio_1", "data": "AAAA"},
                    },
                    {"role": "user", "content": "continue"},
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_audio" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_nonempty_message_audio_on_user() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "hi", "audio": {"id": "audio_u"}},
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_audio" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_message_function_call_null_and_empty() -> None:
    server, thread, port = _server()
    try:
        for function_call in (None, {}):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "prior",
                            "function_call": function_call,
                        },
                        {"role": "user", "content": "continue"},
                    ],
                },
            )
            assert status == 200, (function_call, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_nonempty_message_function_call() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "assistant",
                        "content": "prior",
                        "function_call": {"name": "lookup", "arguments": "{}"},
                    },
                    {"role": "user", "content": "continue"},
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message_function_call" in blob
        assert "tool_calls" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_nonempty_message_function_call_on_user() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": "hi",
                        "function_call": {"name": "lookup", "arguments": "{}"},
                    },
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_function_call" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_message_audio_on_tools_passthrough_path() -> None:
    """Passthrough (tools present) must still fail closed on message audio."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "assistant",
                        "content": "prior",
                        "audio": {"id": "audio_p"},
                    },
                    {"role": "user", "content": "continue"},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_audio" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_null_message_audio_on_tools_passthrough_path() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "assistant", "content": "prior", "audio": None},
                    {"role": "user", "content": "continue"},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
        )
        # mock passthrough may 200 or provider-shaped error; never 400 on null audio
        assert status != 400 or "invalid_message_audio" not in json.dumps(body), body
        assert status in (200, 502, 503) or "choices" in body or "error" in body, body
    finally:
        server.shutdown()
        thread.join(timeout=5)
