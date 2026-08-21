"""OpenAI user field honesty on Completions and chat: empty fail-closed; null omit."""

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

_TEST_AUTH_TOKEN = "openai_user_field_http_honesty_token"  # noqa: S105


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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_completions_accepts_user() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": "hi", "user": "buyer_account_9"},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_empty_user() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": "hi", "user": ""},
        )
        assert status == 400, body
        assert "invalid_user" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_null_user_as_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": "hi", "user": None},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_user() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "hi"}],
                "user": "buyer_account_9",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_empty_user() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "hi"}],
                "user": "  ",
            },
        )
        assert status == 400, body
        assert "invalid_user" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_user() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {
                "model": "mock-planner",
                "input": "semantic unit for buyer search",
                "user": "buyer_account_9",
            },
        )
        assert status == 200, body
        assert body.get("object") == "list"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_empty_user() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": "x", "user": ""},
        )
        assert status == 400, body
        assert "invalid_user" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_accepts_user()
    test_http_completions_rejects_empty_user()
    test_http_completions_accepts_null_user_as_omit()
    test_http_chat_accepts_user()
    test_http_chat_rejects_empty_user()
    test_http_embeddings_accepts_user()
    test_http_embeddings_rejects_empty_user()
    print("ok")
