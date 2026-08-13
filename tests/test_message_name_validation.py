"""OpenAI optional per-message name validation and preservation."""

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
    _validate_messages,
    build_server,
)

_TEST_AUTH_TOKEN = "msg_name_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_messages_preserves_name() -> None:
    rows = _validate_messages(
        [
            {"role": "system", "name": "policy_bot", "content": "Be brief."},
            {"role": "user", "name": "alice", "content": "hello"},
        ]
    )
    assert rows[0]["name"] == "policy_bot"
    assert rows[1]["name"] == "alice"


def test_validate_messages_rejects_empty_name() -> None:
    try:
        _validate_messages([{"role": "user", "name": "  ", "content": "x"}])
        raise AssertionError("expected invalid_message_name")
    except RequestError as exc:
        assert exc.code == "invalid_message_name"
    try:
        _validate_messages([{"role": "user", "name": 1, "content": "x"}])
        raise AssertionError("non-string name")
    except RequestError as exc:
        assert exc.code == "invalid_message_name"


def test_http_message_name_accepted() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [
                        {"role": "system", "name": "policy_bot", "content": "Be brief."},
                        {"role": "user", "name": "buyer_1", "content": "hello"},
                    ],
                    "orchestration": "route",
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert body["object"] == "chat.completion"


def test_http_empty_message_name_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [
                        {"role": "user", "name": "", "content": "hello"},
                    ],
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert body["error"]["code"] == "invalid_message_name"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_messages_preserves_name()
    test_validate_messages_rejects_empty_name()
    test_http_message_name_accepted()
    test_http_empty_message_name_rejected()
    print("ok")
