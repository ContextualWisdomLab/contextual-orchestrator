"""OpenAI Responses temperature and top_p range validation."""

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
    _validate_responses_temperature,
    _validate_responses_top_p,
    build_server,
)

_TEST_AUTH_TOKEN = "resp_samp_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_temperature_top_p() -> None:
    assert _validate_responses_temperature({"temperature": 0.7}) == 0.7
    assert _validate_responses_temperature({"temperature": 0}) == 0.0
    assert _validate_responses_temperature({"temperature": 2}) == 2.0
    try:
        _validate_responses_temperature({"temperature": 2.5})
        raise AssertionError("high")
    except RequestError as exc:
        assert exc.code == "invalid_temperature"
    try:
        _validate_responses_temperature({"temperature": True})
        raise AssertionError("bool")
    except RequestError as exc:
        assert exc.code == "invalid_temperature"
    assert _validate_responses_top_p({"top_p": 1}) == 1.0
    assert _validate_responses_top_p({"top_p": 0.1}) == 0.1
    try:
        _validate_responses_top_p({"top_p": 0})
        raise AssertionError("zero")
    except RequestError as exc:
        assert exc.code == "invalid_top_p"


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/responses",
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


def test_http_accepts_sampling() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "input": "hi", "temperature": 0.5, "top_p": 0.9},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_bad_top_p() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "input": "hi", "top_p": 1.5},
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_top_p"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_temperature_top_p()
    test_http_accepts_sampling()
    test_http_rejects_bad_top_p()
    print("ok")
