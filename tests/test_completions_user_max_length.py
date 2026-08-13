"""Legacy Completions user end-user id: non-empty string ≤64 chars."""

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
    _MAX_COMPLETIONS_USER_CHARS,
    _validate_completions_user,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_user_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_completions_user() -> None:
    assert _MAX_COMPLETIONS_USER_CHARS == 64
    assert _validate_completions_user({}) is None
    assert _validate_completions_user({"user": "tenant_a"}) == "tenant_a"
    assert _validate_completions_user({"user": "u" * 64}) == "u" * 64
    try:
        _validate_completions_user({"user": ""})
        raise AssertionError("expected invalid_user empty")
    except RequestError as exc:
        assert exc.code == "invalid_user"
    try:
        _validate_completions_user({"user": "   "})
        raise AssertionError("expected invalid_user whitespace")
    except RequestError as exc:
        assert exc.code == "invalid_user"
    try:
        _validate_completions_user({"user": "u" * 65})
        raise AssertionError("expected invalid_user oversize")
    except RequestError as exc:
        assert exc.code == "invalid_user"
    try:
        _validate_completions_user({"user": 12})
        raise AssertionError("expected invalid_user type")
    except RequestError as exc:
        assert exc.code == "invalid_user"


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/completions",
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


def test_http_rejects_oversize_user() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "user": "x" * 65},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_user"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_user_at_cap() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello world",
                "user": "u" * 64,
            },
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert body["choices"][0]["text"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_completions_user()
    test_http_rejects_oversize_user()
    test_http_accepts_user_at_cap()
