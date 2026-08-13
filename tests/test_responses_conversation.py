"""OpenAI Responses conversation id validation."""

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
    _validate_responses_conversation,
    build_server,
)

_TEST_AUTH_TOKEN = "resp_conv_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_conversation() -> None:
    assert _validate_responses_conversation({}) is None
    assert _validate_responses_conversation({"conversation": "conv_abc"}) == "conv_abc"
    obj = {"id": "conv_xyz"}
    assert _validate_responses_conversation({"conversation": obj}) == obj
    for bad in ("", "   ", 1, [], {"id": ""}, {"id": 1}, {"name": "x"}):
        try:
            _validate_responses_conversation({"conversation": bad})
            raise AssertionError(f"expected reject for {bad!r}")
        except RequestError as exc:
            assert exc.code == "invalid_conversation"


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
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


def test_http_accepts_conversation_string() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {"model": "mock-generalist", "input": "hi", "conversation": "conv_1"},
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_empty_conversation() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {"model": "mock-generalist", "input": "hi", "conversation": ""},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_conversation"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_conversation()
    test_http_accepts_conversation_string()
    test_http_rejects_empty_conversation()
    print("ok")
