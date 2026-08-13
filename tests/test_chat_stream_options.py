"""Chat Completions stream_options requires stream=true; shape-validated."""

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

_TEST_AUTH_TOKEN = "chat_stream_opts_token"  # noqa: S105


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


def test_http_chat_rejects_stream_options_without_stream() -> None:
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
                "stream_options": {"include_usage": True},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_stream_options"
        assert "stream=true" in body["error"]["message"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_object_stream_options() -> None:
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
                "stream": True,
                "stream_options": "include_usage",
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_stream_options"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_stream_options_fields() -> None:
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
                "stream": True,
                "stream_options": {"include_usage": True, "extra": 1},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_stream_options"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_stream_options_with_stream_true() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        # stream=true on route path returns SSE; for non-route (conduct) it may still stream or complete.
        # would_route with simple message -> likely route -> SSE. urllib may not parse SSE as JSON.
        # Use a body that still validates stream_options then hits stream path.
        # We only need to confirm validation passes; stream response is not JSON.
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "mock-generalist",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                # SSE path returns 200
                assert response.status == 200
                raw = response.read().decode("utf-8")
                assert "data:" in raw or raw  # streamed chunks
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8")
            raise AssertionError(f"unexpected {exc.code}: {payload}") from exc
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_stream_options_without_stream()
    test_http_chat_rejects_non_object_stream_options()
    test_http_chat_rejects_unknown_stream_options_fields()
    test_http_chat_accepts_stream_options_with_stream_true()
