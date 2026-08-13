"""OpenAI Responses truncation auto|disabled validation."""

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
    _validate_truncation,
    build_server,
)

_TEST_AUTH_TOKEN = "truncation_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_truncation() -> None:
    assert _validate_truncation({}) is None
    assert _validate_truncation({"truncation": "auto"}) == "auto"
    assert _validate_truncation({"truncation": "disabled"}) == "disabled"
    try:
        _validate_truncation({"truncation": "drop"})
        raise AssertionError("expected invalid_truncation")
    except RequestError as exc:
        assert exc.code == "invalid_truncation"
    try:
        _validate_truncation({"truncation": True})
        raise AssertionError("expected invalid_truncation")
    except RequestError as exc:
        assert exc.code == "invalid_truncation"


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


def test_http_responses_rejects_invalid_truncation() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-generalist",
                "input": "hi",
                "truncation": "drop_old",
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_truncation"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_truncation_auto() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-generalist",
                "input": "hi",
                "truncation": "auto",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_truncation()
    test_http_responses_rejects_invalid_truncation()
    test_http_responses_accepts_truncation_auto()
    print("ok")
