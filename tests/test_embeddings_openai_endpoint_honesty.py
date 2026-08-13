"""OpenAI /v1/embeddings honesty: list shape, input/model required, fail-closed knobs."""

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

_TEST_AUTH_TOKEN = "embeddings_openai_endpoint_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
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
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_embeddings_string_input_openai_list_shape() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "text-embedding-test", "input": "buyer search query about invoices"},
        )
        assert status == 200, body
        assert body.get("object") == "list"
        assert isinstance(body.get("data"), list) and len(body["data"]) == 1
        item = body["data"][0]
        assert item.get("object") == "embedding"
        assert item.get("index") == 0
        assert isinstance(item.get("embedding"), list) and len(item["embedding"]) > 0
        assert body.get("model") == "text-embedding-test"
        usage = body.get("usage") or {}
        assert "prompt_tokens" in usage and "total_tokens" in usage
        assert usage["total_tokens"] >= 0
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_array_input_preserves_order() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "text-embedding-test",
                "input": ["first document chunk", "second document chunk"],
            },
        )
        assert status == 200, body
        assert len(body["data"]) == 2
        assert [item["index"] for item in body["data"]] == [0, 1]
        assert all(isinstance(item["embedding"], list) and item["embedding"] for item in body["data"])
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_encoding_format_float() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "text-embedding-test",
                "input": "float vectors only",
                "encoding_format": "float",
            },
        )
        assert status == 200, body
        assert body["data"][0]["embedding"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_encoding_format_base64() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "text-embedding-test",
                "input": "x",
                "encoding_format": "base64",
            },
        )
        assert status == 400, body
        assert "invalid_encoding_format" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_dimensions() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "text-embedding-test", "input": "x", "dimensions": 256},
        )
        assert status == 400, body
        assert "invalid_dimensions" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_missing_input() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "text-embedding-test"})
        assert status == 400, body
        assert "invalid_input" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_missing_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"input": "no model"})
        assert status == 400, body
        assert "invalid_model" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_inputs_alias() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "text-embedding-test", "inputs": ["batch only key"]},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_input" in blob or "unknown" in blob.lower()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_empty_string_input() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "text-embedding-test", "input": "   "},
        )
        assert status == 400, body
        assert "invalid_input" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_embeddings_string_input_openai_list_shape()
    test_http_embeddings_array_input_preserves_order()
    test_http_embeddings_accepts_encoding_format_float()
    test_http_embeddings_rejects_encoding_format_base64()
    test_http_embeddings_rejects_dimensions()
    test_http_embeddings_rejects_missing_input()
    test_http_embeddings_rejects_missing_model()
    test_http_embeddings_rejects_inputs_alias()
    test_http_embeddings_rejects_empty_string_input()
    print("ok")
