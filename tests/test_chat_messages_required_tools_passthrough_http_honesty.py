"""Tools passthrough must require a non-empty chat messages array.

``_validate_messages`` is skipped when ``tools`` / ``response_format`` force
single-agent passthrough. Missing, JSON null, non-list, or empty ``messages``
must still fail closed so an SDK tool-calling body cannot bill a completion
with no prompt.
"""

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

_TEST_AUTH_TOKEN = "chat_messages_required_tools_passthrough_token"  # noqa: S105

_LOOKUP_TOOLS = [
    {
        "type": "function",
        "function": {"name": "lookup_balance", "parameters": {"type": "object"}},
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


def test_http_chat_rejects_empty_messages_with_tools() -> None:
    """Empty messages + tools must not proxy a billed completion with no prompt."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_message" in blob
        assert "non-empty" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_missing_messages_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_null_messages_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": None,
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_list_messages_with_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": "look up the invoice",
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        assert "invalid_message" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_empty_messages_with_tools()
    test_http_chat_rejects_missing_messages_with_tools()
    test_http_chat_rejects_null_messages_with_tools()
    test_http_chat_rejects_non_list_messages_with_tools()
    print("ok")
