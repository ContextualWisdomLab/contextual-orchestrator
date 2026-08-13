"""Cap max_tokens / max_completion_tokens at 1_048_576."""

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
    _MAX_OUTPUT_TOKENS_CAP,
    _validate_max_tokens_upper_bound,
    build_server,
)

_TEST_AUTH_TOKEN = "max_tokens_cap_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_max_tokens_upper_bound() -> None:
    assert _MAX_OUTPUT_TOKENS_CAP == 1_048_576
    _validate_max_tokens_upper_bound({})
    _validate_max_tokens_upper_bound({"max_tokens": 64})
    _validate_max_tokens_upper_bound({"max_completion_tokens": _MAX_OUTPUT_TOKENS_CAP})
    try:
        _validate_max_tokens_upper_bound({"max_tokens": _MAX_OUTPUT_TOKENS_CAP + 1})
        raise AssertionError("expected invalid_max_tokens over cap")
    except RequestError as exc:
        assert exc.code == "invalid_max_tokens"
    try:
        _validate_max_tokens_upper_bound({"max_completion_tokens": 0})
        raise AssertionError("expected invalid_max_tokens zero")
    except RequestError as exc:
        assert exc.code == "invalid_max_tokens"
    try:
        _validate_max_tokens_upper_bound({"max_tokens": True})
        raise AssertionError("expected invalid_max_tokens bool")
    except RequestError as exc:
        assert exc.code == "invalid_max_tokens"


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


def test_http_rejects_over_cap_max_tokens() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": _MAX_OUTPUT_TOKENS_CAP + 1,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_max_tokens"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_max_tokens_at_cap() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 128,
            },
        )
        assert status == 200, body
        assert body["choices"][0]["message"]["content"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_max_tokens_upper_bound()
    test_http_rejects_over_cap_max_tokens()
    test_http_accepts_max_tokens_at_cap()
