"""OpenAI max_tokens / max_completion_tokens validation on chat completions."""

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
    _validate_max_tokens_fields,
    build_server,
)

_TEST_AUTH_TOKEN = "max_tokens_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_max_tokens_fields() -> None:
    assert _validate_max_tokens_fields({}) is None
    assert _validate_max_tokens_fields({"max_tokens": 32}) == 32
    assert _validate_max_tokens_fields({"max_completion_tokens": 64}) == 64
    assert _validate_max_tokens_fields({"max_tokens": 16, "max_completion_tokens": 16}) == 16
    try:
        _validate_max_tokens_fields({"max_tokens": 0})
        raise AssertionError("zero")
    except RequestError as exc:
        assert exc.code == "invalid_max_tokens"
    try:
        _validate_max_tokens_fields({"max_tokens": 8, "max_completion_tokens": 16})
        raise AssertionError("conflict")
    except RequestError as exc:
        assert exc.code == "invalid_max_tokens"
    try:
        _validate_max_tokens_fields({"max_completion_tokens": True})
        raise AssertionError("bool")
    except RequestError as exc:
        assert exc.code == "invalid_max_tokens"


def test_http_max_tokens_accepted() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "orchestration": "route",
                    "max_tokens": 64,
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


def test_http_max_tokens_conflict_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "max_tokens": 10,
                    "max_completion_tokens": 20,
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
            assert body["error"]["code"] == "invalid_max_tokens"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_max_tokens_fields()
    test_http_max_tokens_accepted()
    test_http_max_tokens_conflict_rejected()
    print("ok")
