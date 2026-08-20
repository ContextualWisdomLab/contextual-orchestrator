"""Whole-float token-id coerce honesty for Completions prompts and embeddings.

JS/form SDKs often serialize token integers as whole floats (``1.0``). OpenAI
token arrays are non-negative integers; this gateway coerces whole floats and
still fails closed on bools, negatives, and non-integral floats.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import (
    SecurityConfig,
    _coerce_embedding_token_sequence,
    _coerce_token_id,
    _embedding_token_sequence_to_text,
    _validate_completion_prompt,
    _validate_embeddings_inputs,
    build_server,
)

_TEST_AUTH_TOKEN = "token_id_whole_float_coerce_http_honesty_token"


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


def test_unit_coerce_token_id_whole_float() -> None:
    assert _coerce_token_id(0) == 0
    assert _coerce_token_id(42) == 42
    assert _coerce_token_id(0.0) == 0
    assert _coerce_token_id(7.0) == 7
    assert _coerce_token_id(-1) is None
    assert _coerce_token_id(-1.0) is None
    assert _coerce_token_id(1.5) is None
    assert _coerce_token_id(True) is None
    assert _coerce_token_id(False) is None
    assert _coerce_token_id("1") is None


def test_unit_coerce_token_sequence_whole_float() -> None:
    assert _coerce_embedding_token_sequence([1.0, 2.0, 3.0]) == [1, 2, 3]
    assert _coerce_embedding_token_sequence([1, 2.0, 3]) == [1, 2, 3]
    assert _coerce_embedding_token_sequence([1.5, 2.0]) is None
    assert _coerce_embedding_token_sequence([1.0, -1.0]) is None
    assert _coerce_embedding_token_sequence([True, False]) is None
    assert _embedding_token_sequence_to_text([1, 2]) == "\x1etokens:1,2"
    assert _validate_completion_prompt([1.0, 2.0])[0]["content"] == "\x1etokens:1,2"
    assert _validate_embeddings_inputs({"input": [10.0, 11.0]}) == ["\x1etokens:10,11"]
    assert _validate_embeddings_inputs({"input": [[1.0], [2.0, 3.0]]}) == [
        "\x1etokens:1",
        "\x1etokens:2,3",
    ]


def test_http_completions_accepts_whole_float_token_prompt() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": [1.0, 2.0, 3.0]},
        )
        assert status == 200, body
        assert "choices" in body, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_batch_whole_float_token_prompts() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": [[1.0, 2.0], [3.0], [4, 5.0]]},
        )
        assert status == 200, body
        assert "choices" in body, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_invalid_whole_float_token_prompts() -> None:
    server, thread, port = _server()
    try:
        for value in ([1.0, -1.0], [1.5], [True, 1.0], [1.0, "x"]):
            status, body = _post(
                port,
                "/v1/completions",
                {"model": "mock-planner", "prompt": value},
            )
            assert status == 400, (value, body)
            assert "invalid_prompt" in json.dumps(body), (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_whole_float_token_input() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": [100.0, 200.0]},
        )
        assert status == 200, body
        assert body.get("object") == "list" or "data" in body, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_batch_whole_float_token_inputs() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": [[1.0, 2.0], [3.0]]},
        )
        assert status == 200, body
        data = body.get("data") or []
        assert len(data) == 2, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_rejects_invalid_whole_float_token_inputs() -> None:
    server, thread, port = _server()
    try:
        for value in ([1.0, -2.0], [0.5, 1.0], [False, 1.0]):
            status, body = _post(
                port,
                "/v1/embeddings",
                {"model": "mock-planner", "input": value},
            )
            assert status == 400, (value, body)
            blob = json.dumps(body)
            assert "invalid_input" in blob, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_integer_token_prompt_still_works() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": [9, 8, 7]},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_unit_coerce_token_id_whole_float()
    test_unit_coerce_token_sequence_whole_float()
    test_http_completions_accepts_whole_float_token_prompt()
    test_http_completions_accepts_batch_whole_float_token_prompts()
    test_http_completions_rejects_invalid_whole_float_token_prompts()
    test_http_embeddings_accepts_whole_float_token_input()
    test_http_embeddings_accepts_batch_whole_float_token_inputs()
    test_http_embeddings_rejects_invalid_whole_float_token_inputs()
    test_http_completions_integer_token_prompt_still_works()
    print("ok")
