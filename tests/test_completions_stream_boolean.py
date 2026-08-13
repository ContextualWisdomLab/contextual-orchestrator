"""Legacy Completions stream must be a boolean; true is rejected."""

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
    _validate_completions_stream,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_stream_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_completions_stream() -> None:
    assert _validate_completions_stream({}) is None
    assert _validate_completions_stream({"stream": False}) is False
    try:
        _validate_completions_stream({"stream": True})
        raise AssertionError("expected invalid_stream true")
    except RequestError as exc:
        assert exc.code == "invalid_stream"
    try:
        _validate_completions_stream({"stream": "false"})
        raise AssertionError("expected invalid_stream string")
    except RequestError as exc:
        assert exc.code == "invalid_stream"
    try:
        _validate_completions_stream({"stream": 0})
        raise AssertionError("expected invalid_stream int")
    except RequestError as exc:
        assert exc.code == "invalid_stream"
    try:
        _validate_completions_stream({"stream": 1})
        raise AssertionError("expected invalid_stream int 1")
    except RequestError as exc:
        assert exc.code == "invalid_stream"


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


def test_http_rejects_non_boolean_and_true_stream() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "stream": "yes"},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_stream"

        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "stream": True},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_stream"
        assert "chat/completions" in body["error"]["message"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_stream_false() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello world", "stream": False},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert body["choices"][0]["text"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_completions_stream()
    test_http_rejects_non_boolean_and_true_stream()
    test_http_accepts_stream_false()
