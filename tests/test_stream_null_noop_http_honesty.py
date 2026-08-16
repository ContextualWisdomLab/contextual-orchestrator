"""stream/stream_options null as omit no-ops over HTTP."""

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

_TEST_AUTH_TOKEN = "stream_null_noop_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_stream_null() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "stream null"}],
                "stream": None,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_stream_null_and_false() -> None:
    server, thread, port = _server()
    try:
        for stream in (None, False):
            status, body = _post(
                port,
                "/v1/responses",
                {"model": "mock-planner", "input": "stream val", "stream": stream},
            )
            assert status == 200, (stream, body)
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "stream_options null",
                "stream_options": None,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_stream_true_is_event_stream() -> None:
    server, thread, port = _server()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/responses",
            data=json.dumps(
                {"model": "mock-planner", "input": "stream true", "stream": True}
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            assert response.status == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_stream_null() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": "stream null", "stream": None},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_stream_null()
    test_http_responses_accepts_stream_null_and_false()
    test_http_responses_stream_true_is_event_stream()
    test_http_completions_accepts_stream_null()
    print("ok")
