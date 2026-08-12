"""OpenAI-compatible POST /v1/embeddings for gateway consumers."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.api_contract import OPENAPI_SPEC  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "secret_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def post_json(url: str, payload: dict[str, object], token: str | None = None) -> tuple[int, dict[str, object]]:
    headers = {"content-type": "application/json", "connection": "close"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_embeddings_requires_bearer() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = post_json(
            f"http://127.0.0.1:{port}/v1/embeddings",
            {"model": "contextual-orchestrator", "input": "hello"},
        )
        assert status == 401
        assert body["error"]["code"] == "unauthorized"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_embeddings_returns_openai_shape_for_string_and_array_input() -> None:
    """Buyer path: OpenAI SDKs can embed via the gateway without batch polling."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = post_json(
            f"http://127.0.0.1:{port}/v1/embeddings",
            {"model": "contextual-orchestrator", "input": "hello world"},
            token=_TEST_AUTH_TOKEN,
        )
        assert status == 200
        assert body["object"] == "list"
        assert body["model"] == "contextual-orchestrator"
        assert isinstance(body["data"], list) and len(body["data"]) == 1
        row = body["data"][0]
        assert row["object"] == "embedding"
        assert row["index"] == 0
        assert isinstance(row["embedding"], list) and len(row["embedding"]) >= 1
        assert all(isinstance(value, (int, float)) for value in row["embedding"])
        assert "usage" in body
        assert int(body["usage"]["prompt_tokens"]) >= 0
        assert int(body["usage"]["total_tokens"]) == int(body["usage"]["prompt_tokens"])

        multi_status, multi_body = post_json(
            f"http://127.0.0.1:{port}/v1/embeddings",
            {"model": "contextual-orchestrator", "input": ["alpha", "beta"]},
            token=_TEST_AUTH_TOKEN,
        )
        assert multi_status == 200
        assert len(multi_body["data"]) == 2
        assert [item["index"] for item in multi_body["data"]] == [0, 1]
        # Deterministic local embedder: same text => same vector.
        again_status, again_body = post_json(
            f"http://127.0.0.1:{port}/v1/embeddings",
            {"model": "contextual-orchestrator", "input": "hello world"},
            token=_TEST_AUTH_TOKEN,
        )
        assert again_status == 200
        assert again_body["data"][0]["embedding"] == body["data"][0]["embedding"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_embeddings_rejects_empty_input() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = post_json(
            f"http://127.0.0.1:{port}/v1/embeddings",
            {"model": "contextual-orchestrator", "input": []},
            token=_TEST_AUTH_TOKEN,
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_request"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_openapi_includes_v1_embeddings() -> None:
    assert "/v1/embeddings" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/v1/embeddings"]["post"]["operationId"] == "create_embeddings"


if __name__ == "__main__":
    test_embeddings_requires_bearer()
    test_embeddings_returns_openai_shape_for_string_and_array_input()
    test_embeddings_rejects_empty_input()
    test_openapi_includes_v1_embeddings()
    print("ok")
