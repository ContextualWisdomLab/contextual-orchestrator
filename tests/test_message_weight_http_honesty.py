"""Chat message weight honesty: 0/1/null omit-equivalent; other values fail closed."""

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

_TEST_AUTH_TOKEN = "message_weight_http_honesty_token"  # noqa: S105


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


def test_http_chat_accepts_weight_null_zero_one() -> None:
    server, thread, port = _server()
    try:
        for weight in (None, 0, 1, 0.0, 1.0):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"w={weight!r}", "weight": weight}],
                },
            )
            assert status == 200, (weight, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_weight_out_of_range() -> None:
    server, thread, port = _server()
    try:
        for weight in (2, 0.5, -1):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "bad weight", "weight": weight}],
                },
            )
            assert status == 400, (weight, body)
            assert "invalid_message_weight" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_weight_non_number() -> None:
    server, thread, port = _server()
    try:
        for weight in ("1", True, []):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "bad type", "weight": weight}],
                },
            )
            assert status == 400, (weight, body)
            assert "invalid_message_weight" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_weight_out_of_range_with_tools() -> None:
    """Tools passthrough must not skip message-weight fail-closed checks."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "weighted tool turn", "weight": 0.5}],
                "tools": [
                    {
                        "type": "function",
                        "function": {"name": "lookup_balance", "parameters": {"type": "object"}},
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_weight" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_weight_out_of_range_with_response_format() -> None:
    """response_format passthrough must not skip message-weight fail-closed checks."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "weighted json turn", "weight": 0.5}],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 400, body
        assert "invalid_message_weight" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_weight_null_zero_one()
    test_http_chat_rejects_weight_out_of_range()
    test_http_chat_rejects_weight_non_number()
    test_http_chat_rejects_weight_out_of_range_with_tools()
    test_http_chat_rejects_weight_out_of_range_with_response_format()
    print("ok")
