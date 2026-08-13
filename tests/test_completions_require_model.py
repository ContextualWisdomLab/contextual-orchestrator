"""Completions model is required and must be a non-empty string."""

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
    _validate_completions_model,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_require_model_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_completions_model() -> None:
    assert _validate_completions_model({"model": "mock-generalist"}) == "mock-generalist"
    try:
        _validate_completions_model({})
        raise AssertionError("expected missing model")
    except RequestError as exc:
        assert exc.code == "invalid_model"
    for bad in ("", "   ", 12, True, None):
        try:
            _validate_completions_model({"model": bad})
            raise AssertionError(f"expected invalid_model for {bad!r}")
        except RequestError as exc:
            assert exc.code == "invalid_model"


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


def test_http_rejects_missing_or_empty_model() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(port, {"prompt": "hello"})
        assert status == 400, body
        assert body["error"]["code"] == "invalid_model"

        status, body = _post(port, {"model": "", "prompt": "hello"})
        assert status == 400, body
        assert body["error"]["code"] == "invalid_model"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_model_and_prompt() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello world"},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert body["model"] == "mock-generalist"
        assert body["choices"][0]["text"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_completions_model()
    test_http_rejects_missing_or_empty_model()
    test_http_accepts_model_and_prompt()
