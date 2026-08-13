"""OpenAI-compatible error.type on gateway error responses."""

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
    SecurityConfig,
    _error_payload,
    _openai_error_type,
    build_server,
)

_TEST_AUTH_TOKEN = "error_type_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_openai_error_type_mapping() -> None:
    assert _openai_error_type(401, "unauthorized") == "authentication_error"
    assert _openai_error_type(403, "forbidden") == "permission_error"
    assert _openai_error_type(404, "route_not_found") == "not_found_error"
    assert _openai_error_type(429, "rate_limited") == "rate_limit_error"
    assert _openai_error_type(400, "invalid_message") == "invalid_request_error"
    assert _openai_error_type(500, "internal_error") == "server_error"


def test_error_payload_includes_type_and_code() -> None:
    body = _error_payload("invalid_message", "messages must be a non-empty array", status=400)
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["code"] == "invalid_message"
    assert body["error"]["message"] == "messages must be a non-empty array"
    assert body["error_code"] == "invalid_message"  # legacy dual surface


def test_http_401_is_authentication_error() -> None:
    """Buyer path: OpenAI Python SDK branches on error.type for auth failures."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode("utf-8"),
            headers={"content-type": "application/json", "connection": "close"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected 401")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 401
            assert body["error"]["type"] == "authentication_error"
            assert body["error"]["code"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_400_invalid_message_is_invalid_request_error() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({"messages": []}).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert body["error"]["type"] == "invalid_request_error"
            assert body["error"]["code"] == "invalid_message"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_404_route_is_not_found_error() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/does-not-exist",
            headers={"authorization": f"Bearer {_TEST_AUTH_TOKEN}", "connection": "close"},
            method="GET",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 404
            assert body["error"]["type"] == "not_found_error"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_openai_error_type_mapping()
    test_error_payload_includes_type_and_code()
    test_http_401_is_authentication_error()
    test_http_400_invalid_message_is_invalid_request_error()
    test_http_404_route_is_not_found_error()
    print("ok")
