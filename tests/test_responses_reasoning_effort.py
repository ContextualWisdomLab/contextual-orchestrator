"""OpenAI Responses reasoning_effort enum validation."""

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
    _validate_responses_reasoning_effort,
    build_server,
)

_TEST_AUTH_TOKEN = "resp_re_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_reasoning_effort() -> None:
    assert _validate_responses_reasoning_effort({}) is None
    assert _validate_responses_reasoning_effort({"reasoning_effort": "high"}) == "high"
    assert _validate_responses_reasoning_effort({"reasoning_effort": "minimal"}) == "minimal"
    try:
        _validate_responses_reasoning_effort({"reasoning_effort": "max"})
        raise AssertionError("bad")
    except RequestError as exc:
        assert exc.code == "invalid_reasoning_effort"


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


def test_http_accepts_reasoning_effort() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "input": "hi", "reasoning_effort": "medium"},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_bad_reasoning_effort() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "input": "hi", "reasoning_effort": "ultra"},
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_reasoning_effort"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_reasoning_effort()
    test_http_accepts_reasoning_effort()
    test_http_rejects_bad_reasoning_effort()
    print("ok")
