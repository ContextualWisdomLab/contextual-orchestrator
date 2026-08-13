"""Completions stream_options: requires stream=true (which itself fails closed)."""

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

_TEST_AUTH_TOKEN = "completions_stream_options_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/completions",
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


def test_http_completions_stream_options_without_stream_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hi",
                "stream_options": {"include_usage": False},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream_options" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_stream_true_with_stream_options_fail_closed() -> None:
    """stream=true is unsupported on Completions; stream_options cannot enable it."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hi",
                "stream": True,
                "stream_options": {"include_usage": False},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        # either invalid_stream or invalid_stream_options depending on validation order
        assert "invalid_stream" in blob or "invalid_stream_options" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_stream_options_non_object_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hi",
                "stream": True,
                "stream_options": "nope",
            },
        )
        assert status == 400, body
        assert "invalid_stream" in json.dumps(body) or "invalid_stream_options" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_omits_stream_options_ok() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hi"},
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_stream_options_without_stream_fail_closed()
    test_http_completions_stream_true_with_stream_options_fail_closed()
    test_http_completions_stream_options_non_object_fail_closed()
    test_http_completions_omits_stream_options_ok()
    print("ok")
