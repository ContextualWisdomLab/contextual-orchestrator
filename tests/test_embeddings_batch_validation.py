"""Embeddings batch input limits and model/endpoint shape validation."""

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
    MAX_EMBEDDINGS_BATCH_SIZE,
    RequestError,
    SecurityConfig,
    _validate_batch_requests,
    _validate_embeddings_endpoint,
    _validate_embeddings_inputs,
    _validate_embeddings_model,
    build_server,
)

_TEST_AUTH_TOKEN = "emb_batch_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_embeddings_inputs() -> None:
    assert _validate_embeddings_inputs({"input": "hello"}) == ["hello"]
    assert _validate_embeddings_inputs({"inputs": ["a", "b"]}) == ["a", "b"]
    try:
        _validate_embeddings_inputs({"input": ""})
        raise AssertionError("empty string")
    except RequestError as exc:
        assert exc.code == "invalid_embeddings_input"
    try:
        _validate_embeddings_inputs({"inputs": ["ok", "  "]})
        raise AssertionError("blank item")
    except RequestError as exc:
        assert exc.code == "invalid_embeddings_input"
    try:
        _validate_embeddings_inputs({"inputs": ["x"] * (MAX_EMBEDDINGS_BATCH_SIZE + 1)})
        raise AssertionError("too many")
    except RequestError as exc:
        assert exc.code == "invalid_embeddings_input"
    try:
        _validate_embeddings_inputs({"inputs": ["y" * 8193]})
        raise AssertionError("too long")
    except RequestError as exc:
        assert exc.code == "invalid_embeddings_input"


def test_validate_embeddings_model_and_endpoint() -> None:
    assert _validate_embeddings_model({}) == "contextual-orchestrator"
    assert _validate_embeddings_model({"model": "text-embedding-3-small"}) == "text-embedding-3-small"
    try:
        _validate_embeddings_model({"model": ""})
        raise AssertionError("empty model")
    except RequestError as exc:
        assert exc.code == "invalid_model"
    assert _validate_embeddings_endpoint({}) is None
    assert _validate_embeddings_endpoint({"endpoint": "embeddings"}) == "embeddings"
    try:
        _validate_embeddings_endpoint({"endpoint": "  "})
        raise AssertionError("blank endpoint")
    except RequestError as exc:
        assert exc.code == "invalid_endpoint"


def test_validate_batch_requests_model() -> None:
    body = {
        "requests": [
            {
                "messages": [{"role": "user", "content": "hi"}],
                "model": "mock-generalist",
            }
        ]
    }
    batch = _validate_batch_requests(body, expose_trace=False)
    assert batch[0].model == "mock-generalist"
    try:
        _validate_batch_requests(
            {
                "requests": [
                    {
                        "messages": [{"role": "user", "content": "hi"}],
                        "model": "",
                    }
                ]
            },
            expose_trace=False,
        )
        raise AssertionError("empty model")
    except RequestError as exc:
        assert exc.code == "invalid_model"


def test_http_embeddings_empty_input_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/batch/embeddings",
            data=json.dumps({"input": ["", "ok"], "model": "mock-embed"}).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert body["error"]["code"] == "invalid_embeddings_input"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_happy_path() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/batch/embeddings",
            data=json.dumps(
                {
                    "input": ["hello world", "second doc"],
                    "model": "mock-embed",
                    "endpoint": "embeddings",
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status in {200, 202}
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert "batch_id" in body or "status" in body or "data" in body or "embeddings" in body


if __name__ == "__main__":
    test_validate_embeddings_inputs()
    test_validate_embeddings_model_and_endpoint()
    test_validate_batch_requests_model()
    test_http_embeddings_empty_input_rejected()
    test_http_embeddings_happy_path()
    print("ok")
