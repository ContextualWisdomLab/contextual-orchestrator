"""Chat messages array hard cap of 512 entries (gateway DoS / cost guard)."""

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
    _MAX_CHAT_MESSAGES,
    _validate_messages,
    build_server,
)

_TEST_AUTH_TOKEN = "msg_max_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _msg(i: int) -> dict:
    return {"role": "user", "content": f"m{i}"}


def test_validate_messages_max_count() -> None:
    assert _MAX_CHAT_MESSAGES == 512
    _validate_messages([_msg(0)])
    _validate_messages([_msg(i) for i in range(512)])
    try:
        _validate_messages([_msg(i) for i in range(513)])
        raise AssertionError("expected invalid_message")
    except RequestError as exc:
        assert exc.code == "invalid_message"
        assert "512" in (exc.message or "") or "at most" in (exc.message or "")


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
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_chat_rejects_over_512_messages() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [_msg(i) for i in range(513)],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_message"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_512_messages() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [_msg(i) for i in range(512)],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_messages_max_count()
    test_http_chat_rejects_over_512_messages()
    test_http_chat_accepts_512_messages()
    print("ok")
