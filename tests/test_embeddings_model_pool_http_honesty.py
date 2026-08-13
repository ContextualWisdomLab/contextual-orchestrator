"""Embeddings model must match the agent pool over HTTP (fail-closed)."""

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

_TEST_AUTH_TOKEN = "embeddings_model_pool_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing", "embedding"))]
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


def test_http_embeddings_rejects_model_outside_agent_pool() -> None:
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
        assert "agent pool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_model_in_agent_pool() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": "invoice search chunk"},
        )
        assert status == 200, body
        assert body.get("object") == "list"
        assert body.get("model") == "mock-planner"
        assert isinstance(body.get("data"), list) and body["data"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_rejects_model_outside_agent_pool() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/batch/embeddings",
            {"model": "text-embedding-3-not-deployed", "inputs": ["alpha", "beta"]},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_model" in blob
        assert "agent pool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_accepts_model_in_agent_pool() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/batch/embeddings",
            {"model": "mock-planner", "inputs": ["alpha", "beta"]},
        )
        assert status == 200, body
        assert body.get("status") == "completed"
        assert body.get("model") == "mock-planner"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_embeddings_rejects_model_outside_agent_pool()
    test_http_embeddings_accepts_model_in_agent_pool()
    test_http_batch_embeddings_rejects_model_outside_agent_pool()
    test_http_batch_embeddings_accepts_model_in_agent_pool()
    print("ok")
