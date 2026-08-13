"""Batch embeddings endpoint alias honesty over HTTP (fail-closed)."""

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

_TEST_AUTH_TOKEN = "batch_embeddings_endpoint_http_honesty_token"  # noqa: S105


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


def test_http_batch_embeddings_accepts_omitted_endpoint() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "inputs": ["alpha chunk", "beta chunk"]},
        )
        assert status == 200, body
        assert body.get("status") == "completed"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_accepts_non_empty_endpoint_alias() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["alpha chunk"],
                "endpoint": "/v1/embeddings",
            },
        )
        assert status == 200, body
        assert body.get("status") == "completed"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_empty_endpoint() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["alpha chunk"],
                "endpoint": "   ",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_endpoint" in blob or "endpoint" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_null_endpoint() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["alpha chunk"],
                "endpoint": None,
            },
        )
        assert status == 400, body
        assert "endpoint" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_non_string_endpoint() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["alpha chunk"],
                "endpoint": 123,
            },
        )
        assert status == 400, body
        assert "endpoint" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_overlong_endpoint() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["alpha chunk"],
                "endpoint": "x" * 257,
            },
        )
        assert status == 400, body
        assert "endpoint" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_batch_embeddings_accepts_omitted_endpoint()
    test_http_batch_embeddings_accepts_non_empty_endpoint_alias()
    test_http_batch_embeddings_rejects_empty_endpoint()
    test_http_batch_embeddings_rejects_null_endpoint()
    test_http_batch_embeddings_rejects_non_string_endpoint()
    test_http_batch_embeddings_rejects_overlong_endpoint()
    print("ok")
