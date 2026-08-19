"""Embeddings null optional fields as omit no-ops over HTTP."""

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

_TEST_AUTH_TOKEN = "embeddings_null_optional_noop_http_honesty_token"  # noqa: S105


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


def test_http_embeddings_accepts_null_encoding_format() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {
                "model": "mock-planner",
                "input": "null encoding",
                "encoding_format": None,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_null_dimensions() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {
                "model": "mock-planner",
                "input": "null dims",
                "dimensions": None,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_accepts_null_dimensions() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/batch/embeddings",
            {
                "model": "mock-planner",
                "inputs": ["null dims batch"],
                "dimensions": None,
            },
        )
        assert status in (200, 202), body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_still_rejects_nonzero_dimensions() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {
                "model": "mock-planner",
                "input": "dims 64",
                "dimensions": 64,
            },
        )
        assert status == 400, body
        assert "invalid_dimensions" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_base64_encoding() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {
                "model": "mock-planner",
                "input": "base64",
                "encoding_format": "base64",
            },
        )
        assert status == 200, body
        data = body.get("data") or []
        assert data, body
        emb = data[0].get("embedding")
        assert isinstance(emb, str) and emb, body
    finally:
        server.shutdown()
        thread.join(timeout=5)
