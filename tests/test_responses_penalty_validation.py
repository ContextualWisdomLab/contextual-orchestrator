"""OpenAI Responses presence_penalty and frequency_penalty range validation."""

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
    _validate_responses_penalties,
    build_server,
)

_TEST_AUTH_TOKEN = "resp_pen_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_penalties() -> None:
    assert _validate_responses_penalties({}) == {}
    assert _validate_responses_penalties(
        {"presence_penalty": 0.5, "frequency_penalty": -1}
    ) == {"presence_penalty": 0.5, "frequency_penalty": -1.0}
    try:
        _validate_responses_penalties({"presence_penalty": 3})
        raise AssertionError("high")
    except RequestError as exc:
        assert exc.code == "invalid_presence_penalty"
    try:
        _validate_responses_penalties({"frequency_penalty": True})
        raise AssertionError("bool")
    except RequestError as exc:
        assert exc.code == "invalid_frequency_penalty"


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


def test_http_accepts_penalties() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "hi",
                "presence_penalty": 0.2,
                "frequency_penalty": 0.1,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_out_of_range_frequency() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "input": "hi", "frequency_penalty": -3},
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_frequency_penalty"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_penalties()
    test_http_accepts_penalties()
    test_http_rejects_out_of_range_frequency()
    print("ok")
