"""Completions max_tokens must be a positive integer at most 1_048_576."""

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
    _validate_completions_max_tokens,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_max_tokens_cap_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_completions_max_tokens() -> None:
    assert _validate_completions_max_tokens({}) is None
    assert _validate_completions_max_tokens({"max_tokens": 1}) == 1
    assert _validate_completions_max_tokens({"max_tokens": 1_048_576}) == 1_048_576
    for bad in (0, -1, True, 1.5, "8", 1_048_577):
        try:
            _validate_completions_max_tokens({"max_tokens": bad})
            raise AssertionError(f"expected invalid_max_tokens for {bad!r}")
        except RequestError as exc:
            assert exc.code == "invalid_max_tokens"


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


def test_http_rejects_over_cap_and_non_positive() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "max_tokens": 1_048_577},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_max_tokens"

        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "max_tokens": 0},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_max_tokens"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_capped_max_tokens() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello world", "max_tokens": 16},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert body["choices"][0]["text"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_completions_max_tokens()
    test_http_rejects_over_cap_and_non_positive()
    test_http_accepts_capped_max_tokens()
