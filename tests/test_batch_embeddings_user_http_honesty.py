"""Batch embeddings OpenAI user field honesty over HTTP (fail-closed)."""

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

_TEST_AUTH_TOKEN = "batch_embeddings_user_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing", "embedding"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/batch/embeddings",
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


def test_http_batch_embeddings_accepts_user() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["batch with user"],
                "user": "end-user-batch-1",
            },
        )
        assert status in (200, 202), body
        blob = json.dumps(body)
        assert "unknown_fields" not in blob
        assert "invalid_user" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_accepts_omit_user() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "inputs": ["batch no user"]},
        )
        assert status in (200, 202), body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_empty_user() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["batch empty user"],
                "user": "   ",
            },
        )
        assert status == 400, body
        assert "invalid_user" in json.dumps(body)
        assert "unknown_fields" not in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_null_user() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["batch null user"],
                "user": None,
            },
        )
        assert status == 400, body
        assert "invalid_user" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_user_too_long() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["batch long user"],
                "user": "u" * 65,
            },
        )
        assert status == 400, body
        assert "invalid_user" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)
