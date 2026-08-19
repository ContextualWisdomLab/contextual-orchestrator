"""Embeddings encoding_format and dimensions honesty over HTTP."""

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

_TEST_AUTH_TOKEN = "embeddings_encoding_format_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/embeddings",
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


def test_http_embeddings_accepts_encoding_format_float() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello world",
                "encoding_format": "float",
            },
        )
        assert status == 200, body
        assert body.get("object") == "list" or "data" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_encoding_format_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello world",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_encoding_format_base64() -> None:
    """OpenAI base64 encoding returns string embeddings (float32 LE)."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello world",
                "encoding_format": "base64",
            },
        )
        assert status == 200, body
        emb = (body.get("data") or [{}])[0].get("embedding")
        assert isinstance(emb, str) and emb, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_encoding_format_non_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello world",
                "encoding_format": True,
            },
        )
        assert status == 400, body
        assert "invalid_encoding_format" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_dimensions() -> None:
    """dimensions is not applied; any value fails closed."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello world",
                "dimensions": 256,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_dimensions" in blob
        assert "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_blank_input() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "   ",
            },
        )
        assert status == 400, body
        assert "invalid_input" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_embeddings_accepts_encoding_format_float()
    test_http_embeddings_accepts_encoding_format_omitted()
    test_http_embeddings_accepts_encoding_format_base64()
    test_http_embeddings_rejects_encoding_format_non_string()
    test_http_embeddings_rejects_dimensions()
    test_http_embeddings_rejects_blank_input()
    print("ok")
