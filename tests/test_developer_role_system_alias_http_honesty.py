"""developer message role aliases to system over HTTP."""

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

_TEST_AUTH_TOKEN = "developer_role_system_alias_http_honesty_token"  # noqa: S105


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


def test_http_chat_accepts_developer_as_system_instruction_plane() -> None:
    server, thread, port = _server()
    try:
        for role in ("developer", "DEVELOPER", " Developer "):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [
                        {"role": role, "content": "You are a helpful system."},
                        {"role": "user", "content": "hello"},
                    ],
                },
            )
            assert status == 200, (role, body)
            assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_function_role() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "function", "name": "f", "content": "x"},
                    {"role": "user", "content": "hi"},
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_role" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_developer_as_system_instruction_plane()
    test_http_chat_still_rejects_function_role()
    print("ok")
