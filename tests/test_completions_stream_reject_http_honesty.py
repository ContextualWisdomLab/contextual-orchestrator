"""Legacy Completions stream honesty over HTTP (gateway rejects Completions streaming)."""

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

_TEST_AUTH_TOKEN = "completions_stream_reject_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
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


def test_http_completions_accepts_stream_false() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "hi", "stream": False},
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_stream_true() -> None:
    """Buyers must use /v1/chat/completions for streaming — Completions stream is unsupported."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "hi", "stream": True},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "stream" in blob.lower() or "not supported" in blob.lower()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_non_bool_stream() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "hi", "stream": "yes"},
        )
        assert status == 400, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_omits_stream_ok() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "mock-planner", "prompt": "hi"})
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)
