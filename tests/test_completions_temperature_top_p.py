"""Legacy Completions temperature [0,2] and top_p (0,1] validation."""

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
    _validate_completions_temperature_top_p,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_temp_top_p_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_completions_temperature_top_p() -> None:
    _validate_completions_temperature_top_p({})
    _validate_completions_temperature_top_p({"temperature": 0, "top_p": 1})
    _validate_completions_temperature_top_p({"temperature": 2, "top_p": 0.1})
    try:
        _validate_completions_temperature_top_p({"temperature": 2.5})
        raise AssertionError("expected invalid_temperature high")
    except RequestError as exc:
        assert exc.code == "invalid_temperature"
    try:
        _validate_completions_temperature_top_p({"temperature": True})
        raise AssertionError("expected invalid_temperature bool")
    except RequestError as exc:
        assert exc.code == "invalid_temperature"
    try:
        _validate_completions_temperature_top_p({"top_p": 0})
        raise AssertionError("expected invalid_top_p zero")
    except RequestError as exc:
        assert exc.code == "invalid_top_p"
    try:
        _validate_completions_temperature_top_p({"top_p": 1.1})
        raise AssertionError("expected invalid_top_p high")
    except RequestError as exc:
        assert exc.code == "invalid_top_p"
    try:
        _validate_completions_temperature_top_p({"top_p": "0.5"})
        raise AssertionError("expected invalid_top_p string")
    except RequestError as exc:
        assert exc.code == "invalid_top_p"


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


def test_http_rejects_out_of_range_temperature_and_top_p() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "temperature": 3},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_temperature"

        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "top_p": 0},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_top_p"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_valid_temperature_top_p() -> None:
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
                "temperature": 0.7,
                "top_p": 0.9,
            },
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert body["choices"][0]["text"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_completions_temperature_top_p()
    test_http_rejects_out_of_range_temperature_and_top_p()
    test_http_accepts_valid_temperature_top_p()
