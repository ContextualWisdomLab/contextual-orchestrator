"""Legacy Completions stop: string or up to 4 non-empty strings."""

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
    _MAX_COMPLETIONS_STOP_SEQUENCES,
    _validate_completions_stop_sequences,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_stop_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_completions_stop_sequences() -> None:
    assert _MAX_COMPLETIONS_STOP_SEQUENCES == 4
    assert _validate_completions_stop_sequences({}) is None
    assert _validate_completions_stop_sequences({"stop": "END"}) == ["END"]
    assert _validate_completions_stop_sequences({"stop": ["a", "b", "c", "d"]}) == ["a", "b", "c", "d"]
    try:
        _validate_completions_stop_sequences({"stop": ""})
        raise AssertionError("expected invalid_stop empty string")
    except RequestError as exc:
        assert exc.code == "invalid_stop"
    try:
        _validate_completions_stop_sequences({"stop": []})
        raise AssertionError("expected invalid_stop empty array")
    except RequestError as exc:
        assert exc.code == "invalid_stop"
    try:
        _validate_completions_stop_sequences({"stop": ["a", "b", "c", "d", "e"]})
        raise AssertionError("expected invalid_stop too many")
    except RequestError as exc:
        assert exc.code == "invalid_stop"
    try:
        _validate_completions_stop_sequences({"stop": ["ok", ""]})
        raise AssertionError("expected invalid_stop empty item")
    except RequestError as exc:
        assert exc.code == "invalid_stop"
    try:
        _validate_completions_stop_sequences({"stop": 12})
        raise AssertionError("expected invalid_stop type")
    except RequestError as exc:
        assert exc.code == "invalid_stop"


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


def test_http_rejects_too_many_stop_sequences() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello",
                "stop": ["a", "b", "c", "d", "e"],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_stop"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_stop_string_and_array() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello world", "stop": "###"},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert body["choices"][0]["text"]

        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello world",
                "stop": ["\n", "END"],
            },
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_completions_stop_sequences()
    test_http_rejects_too_many_stop_sequences()
    test_http_accepts_stop_string_and_array()
