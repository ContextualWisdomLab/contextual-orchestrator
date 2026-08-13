"""OpenAI top-level verbosity validation on chat and Responses."""

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
    _validate_verbosity,
    build_server,
)

_TEST_AUTH_TOKEN = "verbosity_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_verbosity_enum() -> None:
    assert _validate_verbosity({}) is None
    assert _validate_verbosity({"verbosity": "low"}) == "low"
    assert _validate_verbosity({"verbosity": "medium"}) == "medium"
    assert _validate_verbosity({"verbosity": "high"}) == "high"
    try:
        _validate_verbosity({"verbosity": "verbose"})
        raise AssertionError("bad")
    except RequestError as exc:
        assert exc.code == "invalid_verbosity"


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


def test_http_chat_accepts_verbosity() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "verbosity": "low",
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_bad_verbosity() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "verbosity": "max",
            },
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_verbosity"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_verbosity() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {"model": "mock-generalist", "input": "hello", "verbosity": "high"},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_verbosity_enum()
    test_http_chat_accepts_verbosity()
    test_http_chat_rejects_bad_verbosity()
    test_http_responses_accepts_verbosity()
    print("ok")
