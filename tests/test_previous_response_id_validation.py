"""OpenAI Responses previous_response_id validation."""

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
    _validate_previous_response_id,
    build_server,
)

_TEST_AUTH_TOKEN = "prev_resp_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_previous_response_id() -> None:
    assert _validate_previous_response_id({}) is None
    assert _validate_previous_response_id({"previous_response_id": "resp_abc"}) == "resp_abc"
    try:
        _validate_previous_response_id({"previous_response_id": ""})
        raise AssertionError("empty")
    except RequestError as exc:
        assert exc.code == "invalid_previous_response_id"
    try:
        _validate_previous_response_id({"previous_response_id": "  "})
        raise AssertionError("blank")
    except RequestError as exc:
        assert exc.code == "invalid_previous_response_id"
    try:
        _validate_previous_response_id({"previous_response_id": "x" * 129})
        raise AssertionError("long")
    except RequestError as exc:
        assert exc.code == "invalid_previous_response_id"
    try:
        _validate_previous_response_id({"previous_response_id": 12})
        raise AssertionError("type")
    except RequestError as exc:
        assert exc.code == "invalid_previous_response_id"


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


def test_http_accepts_previous_response_id() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "continue",
                "previous_response_id": "resp_01JABC",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_blank_previous_response_id() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "continue",
                "previous_response_id": "",
            },
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_previous_response_id"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_previous_response_id()
    test_http_accepts_previous_response_id()
    test_http_rejects_blank_previous_response_id()
    print("ok")
