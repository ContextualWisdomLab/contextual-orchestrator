"""OpenAI user scalar bool/int/float coerce to strings over HTTP."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402
from contextual_orchestrator.server import _validate_completions_user  # noqa: E402

_TEST_AUTH_TOKEN = "user_scalar_coerce_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing", "embedding"))]
    )


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


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_unit_user_scalar_coerce_writeback() -> None:
    body: dict = {"user": 42}
    assert _validate_completions_user(body) == "42"
    assert body["user"] == "42"
    body = {"user": 7.0}
    assert _validate_completions_user(body) == "7"
    assert body["user"] == "7"
    body = {"user": True}
    assert _validate_completions_user(body) == "true"
    body = {"user": False}
    assert _validate_completions_user(body) == "false"
    body = {"user": 1.25}
    assert _validate_completions_user(body) == "1.25"


def test_unit_user_rejects_object() -> None:
    try:
        _validate_completions_user({"user": {"id": "x"}})
        raise AssertionError("expected RequestError")
    except Exception as exc:  # noqa: BLE001 — assert named code
        assert getattr(exc, "code", None) == "invalid_user"


def test_http_chat_accepts_user_int() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "user int"}],
                "user": 12345,
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_user_float_whole() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": "user float", "user": 9.0},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_user_bool() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {"model": "mock-planner", "input": "user bool", "user": True},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_user_int() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {
                "model": "mock-planner",
                "input": "embed user int",
                "user": 99,
            },
        )
        assert status == 200, body
        assert body.get("object") == "list" or "data" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_user_list() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "user list"}],
                "user": ["a"],
            },
        )
        assert status == 400, body
        assert "invalid_user" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_unit_user_scalar_coerce_writeback()
    test_unit_user_rejects_object()
    test_http_chat_accepts_user_int()
    test_http_completions_accepts_user_float_whole()
    test_http_responses_accepts_user_bool()
    test_http_embeddings_accepts_user_int()
    test_http_chat_rejects_user_list()
    print("ok")
