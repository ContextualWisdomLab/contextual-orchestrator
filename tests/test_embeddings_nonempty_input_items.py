"""Embeddings input items must be non-empty strings (sync + batch)."""

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
    InMemoryConfigStore,
    ModelAgent,
    PriceBook,
    TaskOrchestrator,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "embeddings_nonempty_input_items_token"  # noqa: S105


def _serve():
    agents = [
        ModelAgent(
            id="mock_worker",
            model="mock-a",
            base_url="mock://a",
            provider_name="mock",
            tags=("reasoning", "coding", "writing"),
            priority=1,
        )
    ]
    orchestrator = TaskOrchestrator(agents)
    coordinator = CostRoutingCoordinator(
        orchestrator, InMemoryConfigStore(), price_book=PriceBook(InMemoryConfigStore())
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


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


def test_http_sync_embeddings_accepts_nonempty_array() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {
                "model": "text-embedding-test",
                "input": ["invoice line item", "payment remittance note"],
            },
        )
        assert status == 200, body
        assert len(body.get("data") or []) == 2
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_sync_embeddings_rejects_blank_array_item() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "text-embedding-test", "input": ["ok", "   "]},
        )
        assert status == 400, body
        assert "invalid_input" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_sync_embeddings_rejects_blank_string() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "text-embedding-test", "input": "  "},
        )
        assert status == 400, body
        assert "invalid_input" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_blank_item() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            "/v1/batch/embeddings",
            {
                "model": "text-embedding-test",
                "inputs": ["document a", ""],
            },
        )
        assert status == 400, body
        assert "invalid_input" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_accepts_nonempty_inputs() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            "/v1/batch/embeddings",
            {
                "model": "text-embedding-test",
                "inputs": ["document a", "document b"],
            },
        )
        assert status in (200, 202), body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_sync_embeddings_accepts_nonempty_array()
    test_http_sync_embeddings_rejects_blank_array_item()
    test_http_sync_embeddings_rejects_blank_string()
    test_http_batch_embeddings_rejects_blank_item()
    test_http_batch_embeddings_accepts_nonempty_inputs()
    print("ok")
