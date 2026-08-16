"""Chat message unknown-fields and legacy function-role honesty over HTTP."""

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

_TEST_AUTH_TOKEN = "message_unknown_fields_http_honesty_token"  # noqa: S105


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


def test_http_chat_rejects_unknown_message_fields() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": "hello",
                        "participant": "alice",
                        "custom_meta": 1,
                    }
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "unknown_message_fields" in blob
        assert "participant" in blob
        assert "custom_meta" in blob
        # Must not collapse to opaque unknown_fields at the body level.
        assert body.get("error", {}).get("code") != "unknown_fields" or "message" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_known_optional_message_keys() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": "known keys only",
                        "name": "buyer_user",
                        "weight": 1,
                        "refusal": None,
                        "annotations": None,
                        "audio": None,
                        "function_call": None,
                    }
                ],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_legacy_function_role() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "call it"},
                    {
                        "role": "function",
                        "name": "lookup_item",
                        "content": "{\"ok\":true}",
                    },
                ],
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message_role" in blob
        assert "tool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_unknown_message_fields_on_tools_passthrough() -> None:
    """Unknown message keys fail closed even when tools force passthrough."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup_item",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "messages": [
                    {
                        "role": "user",
                        "content": "use tool",
                        "smuggled_field": True,
                    }
                ],
            },
        )
        assert status == 400, body
        assert "unknown_message_fields" in json.dumps(body)
        assert "smuggled_field" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_unknown_message_fields()
    test_http_chat_accepts_known_optional_message_keys()
    test_http_chat_rejects_legacy_function_role()
    test_http_chat_unknown_message_fields_on_tools_passthrough()
    print("ok")
