"""Embeddings token-array input shapes over HTTP."""

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

_TEST_AUTH_TOKEN = "embeddings_token_array_input_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent(
                "general_agent",
                "mock-planner",
                tags=("reasoning", "writing", "embedding"),
            )
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
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_embeddings_accepts_token_id_array() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": [1, 2, 3, 4]},
        )
        assert status == 200, body
        data = body.get("data") or []
        assert len(data) == 1, body
        assert isinstance(data[0].get("embedding"), list), body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_batch_of_token_arrays() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": [[10, 11], [20], [30, 31, 32]]},
        )
        assert status == 200, body
        data = body.get("data") or []
        assert len(data) == 3, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_still_rejects_bool_and_negative_tokens() -> None:
    server, thread, port = _server()
    try:
        for value in ([True, False], [1, -1], [1, "x"], [[1, 2], "hi"]):
            status, body = _post(
                port,
                "/v1/embeddings",
                {"model": "mock-planner", "input": value},
            )
            assert status == 400, (value, body)
            assert "invalid_input" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_batch_embeddings_accepts_token_arrays() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/batch/embeddings",
            {"model": "mock-planner", "inputs": [[1, 2], [3, 4, 5]]},
        )
        assert status in (200, 202), body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_embeddings_accepts_token_id_array()
    test_http_embeddings_accepts_batch_of_token_arrays()
    test_http_embeddings_still_rejects_bool_and_negative_tokens()
    test_http_batch_embeddings_accepts_token_arrays()
    print("ok")
