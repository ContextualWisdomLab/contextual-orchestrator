"""OpenAI Responses store and parallel_tool_calls boolean validation."""

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
    _validate_responses_parallel_tool_calls,
    _validate_responses_store,
    build_server,
)

_TEST_AUTH_TOKEN = "resp_bool_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_store_and_parallel() -> None:
    assert _validate_responses_store({"store": True}) is True
    assert _validate_responses_store({"store": False}) is False
    try:
        _validate_responses_store({"store": "yes"})
        raise AssertionError("string store")
    except RequestError as exc:
        assert exc.code == "invalid_store"
    assert _validate_responses_parallel_tool_calls({"parallel_tool_calls": False}) is False
    try:
        _validate_responses_parallel_tool_calls({"parallel_tool_calls": 1})
        raise AssertionError("int")
    except RequestError as exc:
        assert exc.code == "invalid_parallel_tool_calls"


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


def test_http_accepts_booleans() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "hello",
                "store": True,
                "parallel_tool_calls": False,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_string_store() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "input": "hello", "store": "true"},
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_store"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_store_and_parallel()
    test_http_accepts_booleans()
    test_http_rejects_string_store()
    print("ok")
