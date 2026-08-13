"""Sync /v1/embeddings field parity: encoding_format, dimensions, user."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _validate_embeddings_dimensions,
    _validate_embeddings_encoding_format,
    _validate_embeddings_user,
    build_server,
)

_TEST_AUTH_TOKEN = "emb_sync_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_embeddings_fields() -> None:
    assert _validate_embeddings_encoding_format({}) is None
    assert _validate_embeddings_encoding_format({"encoding_format": "float"}) == "float"
    assert _validate_embeddings_encoding_format({"encoding_format": "base64"}) == "base64"
    try:
        _validate_embeddings_encoding_format({"encoding_format": "json"})
        raise AssertionError("expected invalid_encoding_format")
    except RequestError as exc:
        assert exc.code == "invalid_encoding_format"
    assert _validate_embeddings_dimensions({"dimensions": 8}) == 8
    try:
        _validate_embeddings_dimensions({"dimensions": 0})
        raise AssertionError("expected invalid_dimensions")
    except RequestError as exc:
        assert exc.code == "invalid_dimensions"
    assert _validate_embeddings_user({"user": "acct_1"}) == "acct_1"
    try:
        _validate_embeddings_user({"user": ""})
        raise AssertionError("expected invalid_user")
    except RequestError as exc:
        assert exc.code == "invalid_user"


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


def test_http_sync_rejects_bad_fields() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-generalist", "input": "hello", "encoding_format": "xml"},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_encoding_format"

        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-generalist", "input": "hello", "dimensions": -1},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_dimensions"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_sync_accepts_fields_and_returns_vectors() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {
                "model": "mock-generalist",
                "input": "gateway buyer embedding",
                "encoding_format": "float",
                "dimensions": 16,
                "user": "buyer_acct",
            },
        )
        assert status == 200, body
        assert body["object"] == "list"
        assert isinstance(body["data"], list) and body["data"]
        emb = body["data"][0]["embedding"]
        assert isinstance(emb, list) and len(emb) > 0
        assert all(isinstance(x, (int, float)) for x in emb)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_embeddings_fields()
    test_http_sync_rejects_bad_fields()
    test_http_sync_accepts_fields_and_returns_vectors()
    print("ok")
