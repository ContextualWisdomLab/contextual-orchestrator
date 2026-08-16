"""Message honesty must fail closed on the tools passthrough path."""

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

_TEST_AUTH_TOKEN = "message_honesty_tools_passthrough_http_honesty_token"  # noqa: S105


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


def _lookup_balance_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup_balance",
                "description": "Fetch account balance",
                "parameters": {
                    "type": "object",
                    "properties": {"account_id": {"type": "string"}},
                },
            },
        }
    ]


def test_http_chat_tools_rejects_weight_out_of_range() -> None:
    """Fine-tune weight must not smuggle through tools passthrough."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "weighted tool turn", "weight": 0.5}],
                "tools": _lookup_balance_tools(),
            },
        )
        assert status == 400, body
        assert "invalid_message_weight" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_prefix_true() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "assistant", "content": "partial", "prefix": True},
                ],
                "tools": _lookup_balance_tools(),
            },
        )
        assert status == 400, body
        assert "invalid_message_prefix" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_nonempty_refusal() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "assistant", "content": "", "refusal": "I cannot help with that."},
                ],
                "tools": _lookup_balance_tools(),
            },
        )
        assert status == 400, body
        assert "invalid_message_refusal" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_developer_role() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "developer", "content": "act as a banker"}],
                "tools": _lookup_balance_tools(),
            },
        )
        assert status == 400, body
        assert "invalid_message_role" in json.dumps(body)
        assert "developer" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_empty_user_content() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "   "}],
                "tools": _lookup_balance_tools(),
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_empty_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "named turn", "name": ""}],
                "tools": _lookup_balance_tools(),
            },
        )
        assert status == 400, body
        assert "invalid_message_name" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_input_audio_content_part() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {"data": "AAAA", "format": "wav"},
                            }
                        ],
                    }
                ],
                "tools": _lookup_balance_tools(),
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_weight_null_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "null weight", "weight": None}],
                "tools": _lookup_balance_tools(),
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_tools_rejects_weight_out_of_range()
    test_http_chat_tools_rejects_prefix_true()
    test_http_chat_tools_rejects_nonempty_refusal()
    test_http_chat_tools_rejects_developer_role()
    test_http_chat_tools_rejects_empty_user_content()
    test_http_chat_tools_rejects_empty_name()
    test_http_chat_tools_rejects_input_audio_content_part()
    test_http_chat_tools_accepts_weight_null_omit()
    print("ok")
