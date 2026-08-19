"""Chat/Completions OpenAI metadata shape honesty over HTTP."""

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

_TEST_AUTH_TOKEN = "chat_openai_metadata_http_honesty_token"  # noqa: S105


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


def test_http_chat_accepts_string_metadata() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "meta ok"}],
                "metadata": {"request_id": "req-1", "tenant": "acme"},
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_metadata_non_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "meta string"}],
                "metadata": "not-an-object",
            },
        )
        assert status == 400, body
        assert "invalid_metadata" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_metadata_scalar_values_as_strings() -> None:
    """JS SDKs often send bool/int/float; coerce to OpenAI string values."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "meta scalars"}],
                "metadata": {"count": 3, "ok": True, "ratio": 1.5, "whole": 2.0},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_metadata_nested_object_value() -> None:
    """Nested objects/arrays are not OpenAI metadata values — fail closed."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "meta nested"}],
                "metadata": {"nested": {"a": 1}},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_metadata" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_metadata_too_many_entries() -> None:
    server, thread, port = _server()
    try:
        meta = {f"k{i:02d}": f"v{i}" for i in range(17)}
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "meta overflow"}],
                "metadata": meta,
            },
        )
        assert status == 400, body
        assert "invalid_metadata" in json.dumps(body)
        assert "16" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_metadata_key_too_long() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "meta key long"}],
                "metadata": {"k" * 65: "v"},
            },
        )
        assert status == 400, body
        assert "invalid_metadata" in json.dumps(body)
        assert "64" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_metadata_value_too_long() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "meta value long"}],
                "metadata": {"k": "v" * 513},
            },
        )
        assert status == 400, body
        assert "invalid_metadata" in json.dumps(body)
        assert "512" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_string_metadata() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "legacy meta",
                "metadata": {"source": "cli"},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_metadata_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "no meta"}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_string_metadata()
    test_http_chat_rejects_metadata_non_object()
    test_http_chat_accepts_metadata_scalar_values_as_strings()
    test_http_chat_rejects_metadata_nested_object_value()
    test_http_chat_rejects_metadata_too_many_entries()
    test_http_chat_rejects_metadata_key_too_long()
    test_http_chat_rejects_metadata_value_too_long()
    test_http_completions_accepts_string_metadata()
    test_http_chat_accepts_metadata_omitted()
    print("ok")
