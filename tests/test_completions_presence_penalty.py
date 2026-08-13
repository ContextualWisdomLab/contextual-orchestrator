"""Completions presence_penalty must be a number in [-2, 2]."""

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
    _validate_completions_presence_penalty,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_presence_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_presence_penalty() -> None:
    assert _validate_completions_presence_penalty({}) is None
    assert _validate_completions_presence_penalty({"presence_penalty": -2}) == -2.0
    assert _validate_completions_presence_penalty({"presence_penalty": 2}) == 2.0
    for bad in (-2.1, 2.1, True, "1", None):
        try:
            _validate_completions_presence_penalty({"presence_penalty": bad})
            raise AssertionError(f"expected invalid for {bad!r}")
        except RequestError as exc:
            assert exc.code == "invalid_presence_penalty"


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


def test_http_rejects_out_of_range() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "presence_penalty": 3},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_presence_penalty"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_valid() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello world", "presence_penalty": 0.5},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_presence_penalty()
    test_http_rejects_out_of_range()
    test_http_accepts_valid()
