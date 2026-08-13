"""Legacy Completions best_of must be a positive integer and best_of >= n."""

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
    _validate_completions_best_of,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_best_of_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_completions_best_of() -> None:
    assert _validate_completions_best_of({}) is None
    assert _validate_completions_best_of({"best_of": 1}) == 1
    assert _validate_completions_best_of({"best_of": 3, "n": 2}) == 3
    assert _validate_completions_best_of({"best_of": 2, "n": 2}) == 2

    try:
        _validate_completions_best_of({"best_of": 0})
        raise AssertionError("expected invalid_best_of zero")
    except RequestError as exc:
        assert exc.code == "invalid_best_of"

    try:
        _validate_completions_best_of({"best_of": True})
        raise AssertionError("expected invalid_best_of bool")
    except RequestError as exc:
        assert exc.code == "invalid_best_of"

    try:
        _validate_completions_best_of({"best_of": 1.5})
        raise AssertionError("expected invalid_best_of float")
    except RequestError as exc:
        assert exc.code == "invalid_best_of"

    try:
        _validate_completions_best_of({"best_of": 1, "n": 2})
        raise AssertionError("expected best_of < n")
    except RequestError as exc:
        assert exc.code == "invalid_best_of"
        assert "greater than or equal" in exc.message

    try:
        _validate_completions_best_of({"best_of": 2, "n": True})
        raise AssertionError("expected invalid_n bool")
    except RequestError as exc:
        assert exc.code == "invalid_n"


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


def test_http_rejects_best_of_less_than_n() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "best_of": 1, "n": 2},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_best_of"

        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "best_of": "3"},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_best_of"

        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "best_of": 0},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_best_of"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_best_of_gte_n() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello world", "best_of": 1},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert body["choices"][0]["text"]

        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello world", "best_of": 3, "n": 1},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_completions_best_of()
    test_http_rejects_best_of_less_than_n()
    test_http_accepts_best_of_gte_n()
