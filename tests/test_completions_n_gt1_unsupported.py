"""Completions n > 1 is rejected (single-choice gateway)."""

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
    _validate_completions_n,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_n_gt1_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_n_gt1_rejected() -> None:
    assert _validate_completions_n({}) is None
    assert _validate_completions_n({"n": 1}) == 1
    try:
        _validate_completions_n({"n": 2})
        raise AssertionError("expected n>1 reject")
    except RequestError as exc:
        assert exc.code == "invalid_n"
        assert "not supported" in exc.message


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


def test_http_accepts_n_one() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "n": 1},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert len(body["choices"]) == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_n_gt1() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "n": 3},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_n"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_n_gt1_rejected()
    test_http_accepts_n_one()
    test_http_rejects_n_gt1()
