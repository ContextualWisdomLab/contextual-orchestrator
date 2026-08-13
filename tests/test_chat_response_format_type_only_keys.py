"""Chat response_format type-only key honesty (text/json_object/json_schema)."""

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

_TEST_AUTH_TOKEN = "chat_response_format_type_only_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
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


def test_http_chat_accepts_json_object_type_only_passthrough() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "return json"}],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 200, body
        # Passthrough path preserves response_format in mock echo when present.
        echo = body.get("echo") or {}
        if "response_format" in echo:
            assert echo["response_format"] == {"type": "json_object"}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_text_type_only_passthrough() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "response_format": {"type": "text"},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_json_object_with_sibling_keys() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "response_format": {
                    "type": "json_object",
                    "json_schema": {"name": "x", "schema": {}},
                },
            },
        )
        assert status == 400, body
        err = body.get("error") or body
        assert err.get("code") == "invalid_response_format" or (
            isinstance(err.get("message"), str) and "type field" in err.get("message", "")
        ) or "type field" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_json_schema_with_extra_root_keys() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "item", "schema": {"type": "object"}},
                    "strict": True,
                },
            },
        )
        assert status == 400, body
        assert "invalid_response_format" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_json_object_type_only_passthrough()
    test_http_chat_accepts_text_type_only_passthrough()
    test_http_chat_rejects_json_object_with_sibling_keys()
    test_http_chat_rejects_json_schema_with_extra_root_keys()
    print("ok")
