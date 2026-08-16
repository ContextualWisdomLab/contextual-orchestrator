"""Chat/Completions unknown request fields honesty over HTTP (fail-closed)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "chat_unknown_fields_http_honesty_token"  # noqa: S105


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


def test_http_chat_rejects_unknown_request_field() -> None:
    """Buyers must not believe unsupported OpenAI-adjacent knobs were applied."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "unknown knob"}],
                "unsupported_client_knob": "demo-1",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "unknown_fields" in blob
        assert "unsupported_client_knob" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_multiple_unknown_fields() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "two unknowns"}],
                "unsupported_client_knob": "cache-1",
                "another_unsupported_knob": "safety-1",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "unknown_fields" in blob
        assert "unsupported_client_knob" in blob or "safety_identifier" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_unknown_request_field() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "legacy unknown",
                "not_a_real_completions_field": True,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "unknown_fields" in blob
        assert "not_a_real_completions_field" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_audio_with_named_error() -> None:
    """audio is allowed as a named unsupported field (not opaque unknown_fields)."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "legacy audio",
                "audio": {"voice": "alloy"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_audio" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_stream_non_boolean() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "stream string"}],
                "stream": "yes",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "stream must be a boolean" in blob or "invalid_request" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_invalid_mode() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bad mode"}],
                "mode": "turbo",
            },
        )
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_known_fields_only() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "known only"}],
                "temperature": 0.5,
                "mode": "route",
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_unknown_request_field()
    test_http_chat_rejects_multiple_unknown_fields()
    test_http_completions_rejects_unknown_request_field()
    test_http_completions_rejects_audio_with_named_error()
    test_http_chat_rejects_stream_non_boolean()
    test_http_chat_rejects_invalid_mode()
    test_http_chat_accepts_known_fields_only()
    print("ok")
