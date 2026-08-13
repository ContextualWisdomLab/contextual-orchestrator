"""Legacy Completions presence_penalty and frequency_penalty in [-2, 2]."""

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
    _validate_completions_penalties,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_penalties_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_completions_penalties() -> None:
    _validate_completions_penalties({})
    _validate_completions_penalties({"presence_penalty": -2, "frequency_penalty": 2})
    _validate_completions_penalties({"presence_penalty": 0, "frequency_penalty": 0.5})
    try:
        _validate_completions_penalties({"presence_penalty": -2.1})
        raise AssertionError("expected invalid_presence_penalty")
    except RequestError as exc:
        assert exc.code == "invalid_presence_penalty"
    try:
        _validate_completions_penalties({"frequency_penalty": 3})
        raise AssertionError("expected invalid_frequency_penalty")
    except RequestError as exc:
        assert exc.code == "invalid_frequency_penalty"
    try:
        _validate_completions_penalties({"presence_penalty": True})
        raise AssertionError("expected invalid_presence_penalty bool")
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


def test_http_rejects_out_of_range_penalties() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "frequency_penalty": 2.5},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_frequency_penalty"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_valid_penalties() -> None:
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
                "presence_penalty": 0.2,
                "frequency_penalty": -0.1,
            },
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert body["choices"][0]["text"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_completions_penalties()
    test_http_rejects_out_of_range_penalties()
    test_http_accepts_valid_penalties()
