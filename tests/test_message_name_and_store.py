"""OpenAI optional message name and store flag on chat completions."""

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
    _validate_store_flag,
    build_server,
)

_TEST_AUTH_TOKEN = "name_store_token"  # noqa: S105


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
    assert rows[1]["content"] == "hello"


def test_validate_messages_rejects_empty_name() -> None:
    try:
        _validate_messages([{"role": "user", "name": "  ", "content": "x"}])
        raise AssertionError("expected invalid_message_name")
    except RequestError as exc:
        assert exc.code == "invalid_message_name"


def test_validate_store_flag() -> None:
    assert _validate_store_flag({}) is None
    assert _validate_store_flag({"store": True}) is True
    assert _validate_store_flag({"store": False}) is False
    try:
        _validate_store_flag({"store": "yes"})
        raise AssertionError("expected invalid_store")
    except RequestError as exc:
        assert exc.code == "invalid_store"


def test_http_store_and_name_accepted() -> None:
    """Buyer path: multi-user SDKs send name; store flag is boolean."""
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
                        {"role": "user", "name": "buyer_ops", "content": "status please"},
                    ],
                    "orchestration": "route",
                    "store": False,
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


def test_http_store_non_bool_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "store": 1,
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
            assert body["error"]["code"] == "invalid_store"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_messages_preserves_name()
    test_validate_messages_rejects_empty_name()
    test_validate_store_flag()
    test_http_store_and_name_accepted()
    test_http_store_non_bool_rejected()
    print("ok")
