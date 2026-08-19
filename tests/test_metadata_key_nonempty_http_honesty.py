"""OpenAI metadata empty/whitespace key fail-closed honesty over HTTP."""

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
    build_server,
    _validate_openai_metadata,
)

_TEST_AUTH_TOKEN = "metadata_key_nonempty_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
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


def test_validate_rejects_empty_metadata_key() -> None:
    try:
        _validate_openai_metadata({"metadata": {"": "value"}})
        raise AssertionError("expected RequestError")
    except RequestError as exc:
        assert exc.code == "invalid_metadata"
        assert "non-empty" in exc.message


def test_validate_rejects_whitespace_metadata_key() -> None:
    try:
        _validate_openai_metadata({"metadata": {"   ": "value"}})
        raise AssertionError("expected RequestError")
    except RequestError as exc:
        assert exc.code == "invalid_metadata"
        assert "non-empty" in exc.message


def test_validate_accepts_normal_metadata_key() -> None:
    body = {"metadata": {"tenant_id": "acme"}}
    assert _validate_openai_metadata(body) == {"tenant_id": "acme"}


def test_http_chat_rejects_empty_metadata_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "meta empty key"}],
                "metadata": {"": "orphan"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_metadata" in blob
        assert "unknown_fields" not in blob
        assert "non-empty" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_whitespace_metadata_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "meta ws key"}],
                "metadata": {"  ": "orphan"},
            },
        )
        assert status == 400, body
        assert "invalid_metadata" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_normal_metadata() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "meta ok"}],
                "metadata": {"tenant_id": "acme"},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_empty_metadata_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "meta empty key responses",
                "metadata": {"": "orphan"},
            },
        )
        assert status == 400, body
        assert "invalid_metadata" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_rejects_empty_metadata_key()
    test_validate_rejects_whitespace_metadata_key()
    test_validate_accepts_normal_metadata_key()
    test_http_chat_rejects_empty_metadata_key()
    test_http_chat_rejects_whitespace_metadata_key()
    test_http_chat_accepts_normal_metadata()
    test_http_responses_rejects_empty_metadata_key()
    print("ok")
