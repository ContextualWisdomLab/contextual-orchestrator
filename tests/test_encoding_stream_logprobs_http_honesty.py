"""encoding_format casefold, Responses stream string-bool, Completions logprobs 0/false omit."""

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

_TEST_AUTH_TOKEN = "encoding_stream_logprobs_http_honesty_token"  # noqa: S105


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
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_embeddings_accepts_casefold_float_encoding_format() -> None:
    server, thread, port = _server()
    try:
        for value in ("float", "FLOAT", " Float ", "Float"):
            status, body = _post(
                port,
                "/v1/embeddings",
                {"model": "mock-planner", "input": "enc", "encoding_format": value},
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_base64_encoding_format() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": "enc", "encoding_format": "base64"},
        )
        assert status == 200, body
        emb = (body.get("data") or [{}])[0].get("embedding")
        assert isinstance(emb, str) and emb, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_stream_false_string_forms() -> None:
    server, thread, port = _server()
    try:
        for value in (False, "false", "FALSE", "0", 0, None, ""):
            status, body = _post(
                port,
                "/v1/responses",
                {"model": "mock-planner", "input": "stream false", "stream": value},
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_stream_true_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {"model": "mock-planner", "input": "stream true", "stream": "true"},
        )
        assert status == 400, body
        assert "invalid_stream" in json.dumps(body)
        assert "not supported" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_logprobs_false_zero_omit_forms() -> None:
    server, thread, port = _server()
    try:
        for value in (False, "false", "FALSE", "0", 0, 0.0, None):
            status, body = _post(
                port,
                "/v1/completions",
                {"model": "mock-planner", "prompt": "lp", "logprobs": value},
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_logprobs_true_and_nonzero() -> None:
    server, thread, port = _server()
    try:
        for value in (True, "true", 1, 5):
            status, body = _post(
                port,
                "/v1/completions",
                {"model": "mock-planner", "prompt": "lp bad", "logprobs": value},
            )
            assert status == 400, (value, body)
            assert "invalid_logprobs" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)
