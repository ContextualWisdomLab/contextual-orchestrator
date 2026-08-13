"""OpenAI per-message name non-empty and at most 64 characters."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _MAX_MESSAGE_NAME_CHARS,
    _validate_messages,
    build_server,
)

_TEST_AUTH_TOKEN = "msg_name_max_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_message_name_max_length() -> None:
    assert _MAX_MESSAGE_NAME_CHARS == 64
    rows = _validate_messages(
        [{"role": "user", "content": "hi", "name": "alice"}]
    )
    assert rows[0]["name"] == "alice"
    _validate_messages([{"role": "user", "content": "hi", "name": "n" * 64}])
    try:
        _validate_messages([{"role": "user", "content": "hi", "name": ""}])
        raise AssertionError("expected invalid_message_name empty")
    except RequestError as exc:
        assert exc.code == "invalid_message_name"
    try:
        _validate_messages([{"role": "user", "content": "hi", "name": "n" * 65}])
        raise AssertionError("expected invalid_message_name length")
    except RequestError as exc:
        assert exc.code == "invalid_message_name"


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


def test_http_rejects_oversized_message_name() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi", "name": "x" * 65}],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_message_name"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_name_at_cap() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hello", "name": "y" * 64}],
            },
        )
        assert status == 200, body
        assert body["choices"][0]["message"]["content"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_message_name_max_length()
    test_http_rejects_oversized_message_name()
    test_http_accepts_name_at_cap()
    print("ok")
