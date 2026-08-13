"""Embeddings execution identity must match the backend that produced vectors."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    CostRoutingCoordinator,
    LOCAL_HEURISTIC_EMBEDDING_MODEL,
    ModelAgent,
    TaskOrchestrator,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "embeddings_model_pool_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    """Return a pool containing chat and explicitly reserved local-embedding agents."""

    return TaskOrchestrator(
        [
            ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing")),
            ModelAgent(
                "embedding_agent",
                LOCAL_HEURISTIC_EMBEDDING_MODEL,
                tags=("embedding", "offline_test"),
            ),
        ]
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


def test_http_embeddings_rejects_unknown_pool_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "text-embedding-3-not-deployed", "input": "invoice search chunk"},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_model" in blob
        assert "text-embedding-3-not-deployed" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_chat_model_even_when_pool_serves_it() -> None:
    """A chat-capable pool entry must not legitimize a local heuristic vector."""

    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-generalist", "input": "invoice search chunk"},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "local-heuristic-embedding" in blob
        assert "falsely attribute a heuristic vector" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_explicit_local_heuristic_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": LOCAL_HEURISTIC_EMBEDDING_MODEL, "input": "invoice search chunk"},
        )
        assert status == 200, body
        assert body.get("object") == "list"
        assert body.get("model") == LOCAL_HEURISTIC_EMBEDDING_MODEL
        assert isinstance(body.get("data"), list) and body["data"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_chat_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/batch/embeddings",
            {"model": "mock-generalist", "inputs": ["alpha", "beta"]},
        )
        assert status == 400, body
        assert "falsely attribute a heuristic vector" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_accepts_explicit_local_heuristic_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/batch/embeddings",
            {"model": LOCAL_HEURISTIC_EMBEDDING_MODEL, "inputs": ["alpha body", "beta attachment"]},
        )
        assert status == 200, body
        assert body.get("status") == "completed"
        assert body.get("model") == LOCAL_HEURISTIC_EMBEDDING_MODEL
        assert isinstance(body.get("embeddings"), list)
        assert len(body["embeddings"]) == 2
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_embedding_ledger_ignores_spoofed_execution_identity() -> None:
    """Caller attribution cannot rename the model/provider that actually ran."""

    coordinator = CostRoutingCoordinator(build())
    document = coordinator.complete_embeddings_batch(
        ["invoice search chunk"],
        model=LOCAL_HEURISTIC_EMBEDDING_MODEL,
        attribution={
            "account": "buyer_account",
            "model_name": "text-embedding-3-large",
            "provider": "openai",
            "upstream_api": "openai",
        },
    )
    assert document["status"] == "completed"
    rows = coordinator.ledger.store.query(None, None)
    assert len(rows) == 1
    assert rows[0]["model_name"] == LOCAL_HEURISTIC_EMBEDDING_MODEL
    assert rows[0]["provider_name"] == "local_heuristic"
    assert rows[0]["upstream_api"] == "local_heuristic"
    assert rows[0]["account_name"] == "buyer_account"


if __name__ == "__main__":
    test_http_embeddings_rejects_unknown_pool_model()
    test_http_embeddings_rejects_chat_model_even_when_pool_serves_it()
    test_http_embeddings_accepts_explicit_local_heuristic_model()
    test_http_batch_embeddings_rejects_chat_model()
    test_http_batch_embeddings_accepts_explicit_local_heuristic_model()
    test_embedding_ledger_ignores_spoofed_execution_identity()
    print("ok")
