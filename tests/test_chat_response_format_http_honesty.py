"""Chat Completions response_format honesty over HTTP (structured-output shape)."""

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

_TEST_AUTH_TOKEN = "chat_response_format_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
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


def test_http_chat_accepts_response_format_text() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "plain text"}],
                "response_format": {"type": "text"},
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_response_format_json_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "json object mode"}],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_valid_json_schema_response_format() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "structured"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "receipt_line",
                        "schema": {
                            "type": "object",
                            "properties": {"amount": {"type": "number"}},
                        },
                        "strict": True,
                    },
                },
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_response_format_type() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bad type"}],
                "response_format": {"type": "xml"},
            },
        )
        assert status == 400, body
        assert "invalid_response_format" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_json_object_with_sibling_keys() -> None:
    """Buyers must not smuggle extra fields into type-only response_format objects."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "sibling"}],
                "response_format": {"type": "json_object", "strict": True},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_response_format" in blob
        assert "only the type field" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_json_schema_without_schema_body() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "missing schema"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "receipt_line"},
                },
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_response_format" in blob
        assert "schema must be an object" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_object_response_format() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "string fmt"}],
                "response_format": "json",
            },
        )
        assert status == 400, body
        assert "invalid_response_format" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_response_format_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "no format"}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_response_format_text()
    test_http_chat_accepts_response_format_json_object()
    test_http_chat_accepts_valid_json_schema_response_format()
    test_http_chat_rejects_unknown_response_format_type()
    test_http_chat_rejects_json_object_with_sibling_keys()
    test_http_chat_rejects_json_schema_without_schema_body()
    test_http_chat_rejects_non_object_response_format()
    test_http_chat_accepts_response_format_omitted()
    print("ok")
