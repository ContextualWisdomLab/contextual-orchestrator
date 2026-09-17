"""Batch embeddings routing shape honesty over HTTP."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import CostRoutingCoordinator, ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "batch_embeddings_routing_http_honesty_token"  # noqa: S105


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
    orchestrator = build()
    counter = type("ExactSyntheticCounter", (), {"count_text": lambda self, text, model="": len(text)})()
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN), coordinator=CostRoutingCoordinator(orchestrator, embedding_token_counter=counter))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_batch_embeddings_accepts_priority_bulk() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["bulk priority"],
                "routing": {"priority": "bulk"},
            },
        )
        assert status in (200, 202), body
        assert "unknown_fields" not in json.dumps(body)
        assert "invalid_routing" not in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_accepts_channel_batch() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["channel batch"],
                "routing": {"channel": "batch", "latency_tolerant": True},
            },
        )
        assert status in (200, 202), body
        assert "unknown_fields" not in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_invalid_priority() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["bad priority"],
                "routing": {"priority": "urgent"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_routing" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_channel_turbo() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "inputs": ["turbo"],
                "routing": {"channel": "turbo"},
            },
        )
        assert status == 400, body
        assert "invalid_routing" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_baseline_without_routing() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port, {"model": "mock-planner", "inputs": ["baseline"]}
        )
        assert status in (200, 202), body
    finally:
        server.shutdown()
        thread.join(timeout=5)
