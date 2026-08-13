"""Chat stream_options empty object and false flags are accepted no-ops."""

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

_TEST_AUTH_TOKEN = "chat_stream_options_empty_false_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _post_raw(port: int, payload: dict) -> tuple[int, bytes]:
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
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_http_chat_accepts_empty_stream_options_with_stream() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, raw = _post_raw(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
                "stream_options": {},
            },
        )
        assert status == 200, raw.decode("utf-8", errors="replace")
        text = raw.decode("utf-8", errors="replace")
        assert "data:" in text or "chat.completion" in text
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_stream_options_false_flags() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, raw = _post_raw(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
                "stream_options": {
                    "include_usage": False,
                    "include_obfuscation": False,
                },
            },
        )
        assert status == 200, raw.decode("utf-8", errors="replace")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_stream_options_without_stream() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, raw = _post_raw(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "stream_options": {},
            },
        )
        assert status == 400, raw.decode("utf-8", errors="replace")
        body = json.loads(raw.decode("utf-8"))
        assert "stream_options" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_include_usage_true() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, raw = _post_raw(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        )
        assert status == 400, raw.decode("utf-8", errors="replace")
        assert "include_usage" in raw.decode("utf-8")
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_empty_stream_options_with_stream()
    test_http_chat_accepts_stream_options_false_flags()
    test_http_chat_rejects_stream_options_without_stream()
    test_http_chat_rejects_include_usage_true()
    print("ok")
