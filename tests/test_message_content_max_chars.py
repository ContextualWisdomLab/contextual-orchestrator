"""Per-message content hard cap of 1_000_000 characters (gateway DoS guard)."""

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
    _MAX_MESSAGE_CONTENT_CHARS,
    _validate_messages,
    build_server,
)

_TEST_AUTH_TOKEN = "msg_chars_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_message_content_max_chars() -> None:
    assert _MAX_MESSAGE_CONTENT_CHARS == 1_000_000
    _validate_messages([{"role": "user", "content": "ok"}])
    _validate_messages([{"role": "user", "content": "x" * _MAX_MESSAGE_CONTENT_CHARS}])
    try:
        _validate_messages([{"role": "user", "content": "x" * (_MAX_MESSAGE_CONTENT_CHARS + 1)}])
        raise AssertionError("expected invalid_message")
    except RequestError as exc:
        assert exc.code == "invalid_message"
        assert "1000000" in (exc.message or "")


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
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_rejects_oversized_message_content() -> None:
    # Default max_body_bytes is 64KiB; raise it so the content cap is exercised.
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(
            auth_token=_TEST_AUTH_TOKEN,
            max_body_bytes=2_000_000,
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "y" * (_MAX_MESSAGE_CONTENT_CHARS + 1)}],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_message"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_moderate_content() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "z" * 8_000}],
            },
        )
        assert status == 200, body
        assert body["choices"][0]["message"]["content"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_message_content_max_chars()
    test_http_rejects_oversized_message_content()
    test_http_accepts_moderate_content()
    print("ok")
