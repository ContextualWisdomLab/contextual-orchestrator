"""Batch embeddings endpoint alias: omit/non-empty ok; empty/non-string fail-closed."""

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

_TEST_AUTH_TOKEN = "batch_embeddings_endpoint_honesty_token"  # noqa: S105


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


def test_http_batch_embeddings_omits_endpoint() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {"model": "text-embedding-test", "inputs": ["buyer invoice chunk one"]},
        )
        assert status in (200, 202), body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_accepts_endpoint_alias() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {
                "model": "text-embedding-test",
                "inputs": ["buyer invoice chunk two"],
                "endpoint": "/v1/embeddings",
            },
        )
        assert status in (200, 202), body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_empty_endpoint() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {
                "model": "text-embedding-test",
                "inputs": ["x"],
                "endpoint": "   ",
            },
        )
        assert status == 400, body
        assert "invalid_endpoint" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_null_endpoint() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {
                "model": "text-embedding-test",
                "inputs": ["x"],
                "endpoint": None,
            },
        )
        assert status == 400, body
        assert "invalid_endpoint" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_non_string_endpoint() -> None:
    server, thread, port = _serve()
    try:
        status, body = _post(
            port,
            {
                "model": "text-embedding-test",
                "inputs": ["x"],
                "endpoint": 1,
            },
        )
        assert status == 400, body
        assert "invalid_endpoint" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_batch_embeddings_omits_endpoint()
    test_http_batch_embeddings_accepts_endpoint_alias()
    test_http_batch_embeddings_rejects_empty_endpoint()
    test_http_batch_embeddings_rejects_null_endpoint()
    test_http_batch_embeddings_rejects_non_string_endpoint()
    print("ok")
