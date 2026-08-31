"""Embeddings encoding_format base64 (float32 LE) over HTTP."""

from __future__ import annotations

import base64
import json
import struct
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import CostRoutingCoordinator, ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "embeddings_encoding_format_base64_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    orchestrator = build()
    counter = type("ExactSyntheticCounter", (), {"count_text": lambda self, text, model="": len(text)})()
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
        coordinator=CostRoutingCoordinator(orchestrator, embedding_token_counter=counter),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_embeddings_base64_roundtrips_float32() -> None:
    server, thread, port = _server()
    try:
        status_f, body_f = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello base64",
                "encoding_format": "float",
            },
        )
        assert status_f == 200, body_f
        floats = body_f["data"][0]["embedding"]
        assert isinstance(floats, list) and floats

        status_b, body_b = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello base64",
                "encoding_format": "BASE64",
            },
        )
        assert status_b == 200, body_b
        encoded = body_b["data"][0]["embedding"]
        assert isinstance(encoded, str) and encoded
        raw = base64.b64decode(encoded)
        assert len(raw) == len(floats) * 4
        decoded = list(struct.unpack(f"<{len(floats)}f", raw))
        assert len(decoded) == len(floats)
        for a, b in zip(floats, decoded):
            assert abs(float(a) - float(b)) < 1e-5
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_still_rejects_unknown_encoding_format() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "bad fmt",
                "encoding_format": "json",
            },
        )
        assert status == 400, body
        assert "invalid_encoding_format" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_embeddings_base64_roundtrips_float32()
    test_http_embeddings_still_rejects_unknown_encoding_format()
    print("ok")
