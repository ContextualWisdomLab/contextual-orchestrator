"""Legacy OpenAI functions array hard cap of 128 entries."""

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
    _validate_functions_max_count,
    build_server,
)

_TEST_AUTH_TOKEN = "fn_max_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _fn(i: int) -> dict:
    return {"name": f"fn_{i}", "parameters": {"type": "object", "properties": {}}}


def test_validate_functions_max_count() -> None:
    _validate_functions_max_count({})
    _validate_functions_max_count({"functions": [_fn(0)]})
    _validate_functions_max_count({"functions": [_fn(i) for i in range(128)]})
    try:
        _validate_functions_max_count({"functions": [_fn(i) for i in range(129)]})
        raise AssertionError("expected invalid_functions")
    except RequestError as exc:
        assert exc.code == "invalid_functions"


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


def test_http_chat_rejects_over_128_functions() -> None:
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
                "functions": [_fn(i) for i in range(129)],
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_functions"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_128_functions() -> None:
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
                "functions": [_fn(i) for i in range(128)],
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_functions_max_count()
    test_http_chat_rejects_over_128_functions()
    test_http_chat_accepts_128_functions()
    print("ok")
