"""OpenAI Responses background boolean validation."""

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
    _validate_responses_background,
    build_server,
)

_TEST_AUTH_TOKEN = "resp_bg_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_responses_background() -> None:
    assert _validate_responses_background({}) is None
    assert _validate_responses_background({"background": True}) is True
    assert _validate_responses_background({"background": False}) is False
    try:
        _validate_responses_background({"background": "yes"})
        raise AssertionError("expected invalid_background for string")
    except RequestError as exc:
        assert exc.code == "invalid_background"
    try:
        _validate_responses_background({"background": 1})
        raise AssertionError("expected invalid_background for int")
    except RequestError as exc:
        assert exc.code == "invalid_background"


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


def test_http_responses_accepts_background_false() -> None:
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
                "input": "hello",
                "background": False,
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_non_boolean_background() -> None:
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
                "input": "hello",
                "background": "async",
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_background"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_responses_background()
    test_http_responses_accepts_background_false()
    test_http_responses_rejects_non_boolean_background()
    print("ok")
