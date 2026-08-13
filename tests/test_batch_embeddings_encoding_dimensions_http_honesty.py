"""Batch embeddings encoding_format and dimensions honesty over HTTP (fail-closed)."""

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

_TEST_AUTH_TOKEN = "batch_embeddings_encoding_dimensions_http_honesty_token"  # noqa: S105


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


def test_http_batch_embeddings_accepts_encoding_format_float() -> None:
    """SDK clients that always send encoding_format=float must not hit unknown_fields."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["batch float vectors"],
                "encoding_format": "float",
            },
        )
        assert status in (200, 202), body
        blob = json.dumps(body)
        assert "unknown_fields" not in blob
        assert "invalid_encoding_format" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_accepts_encoding_format_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "inputs": ["batch no encoding_format"]},
        )
        assert status in (200, 202), body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_encoding_format_base64() -> None:
    """Buyers must not believe base64 vectors were returned on the batch path."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["batch base64"],
                "encoding_format": "base64",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_encoding_format" in blob
        assert "unknown_fields" not in blob
        assert "float" in blob
        assert "/v1/batch/embeddings" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_encoding_format_non_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["batch bad encoding_format"],
                "encoding_format": True,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_encoding_format" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_dimensions() -> None:
    """dimensions is not applied on batch either; any value fails closed with a named code."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["batch dimensions"],
                "dimensions": 256,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_dimensions" in blob
        assert "unknown_fields" not in blob
        assert "not supported" in blob
        assert "/v1/batch/embeddings" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_dimensions_null() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["batch dimensions null"],
                "dimensions": None,
            },
        )
        assert status == 400, body
        assert "invalid_dimensions" in json.dumps(body)
        assert "unknown_fields" not in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_batch_embeddings_accepts_encoding_format_float()
    test_http_batch_embeddings_accepts_encoding_format_omitted()
    test_http_batch_embeddings_rejects_encoding_format_base64()
    test_http_batch_embeddings_rejects_encoding_format_non_string()
    test_http_batch_embeddings_rejects_dimensions()
    test_http_batch_embeddings_rejects_dimensions_null()
    print("ok")
