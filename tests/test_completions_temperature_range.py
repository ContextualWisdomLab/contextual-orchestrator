"""Completions temperature must be a number in [0, 2]."""

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
    _validate_completions_temperature,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_temp_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_completions_temperature() -> None:
    assert _validate_completions_temperature({}) is None
    assert _validate_completions_temperature({"temperature": 0}) == 0.0
    assert _validate_completions_temperature({"temperature": 2}) == 2.0
    assert _validate_completions_temperature({"temperature": 0.7}) == 0.7
    for bad in (-0.1, 2.1, True, "1", None):
        try:
            _validate_completions_temperature({"temperature": bad})
            raise AssertionError(f"expected invalid_temperature for {bad!r}")
        except RequestError as exc:
            assert exc.code == "invalid_temperature"


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


def test_http_rejects_out_of_range_temperature() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "temperature": 2.5},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_temperature"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_valid_temperature() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello world", "temperature": 0.2},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert body["choices"][0]["text"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_completions_temperature()
    test_http_rejects_out_of_range_temperature()
    test_http_accepts_valid_temperature()
