"""Completions top_logprobs reject honesty over HTTP (fail-closed)."""

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

_TEST_AUTH_TOKEN = "completions_top_logprobs_reject_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/completions",
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


def test_http_completions_accepts_baseline_without_top_logprobs() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port, {"model": "mock-planner", "prompt": "hello no top_logprobs"}
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_top_logprobs() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "hello top_logprobs",
                "top_logprobs": 5,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_top_logprobs" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_top_logprobs_zero_as_omit() -> None:
    """top_logprobs=0 requests no top alternatives — honest omit no-op."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "hello top_logprobs 0",
                "top_logprobs": 0,
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_boolean_top_logprobs() -> None:
    """JSON false is not integer 0; do not treat it as omit and bill."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "hello top_logprobs false",
                "top_logprobs": False,
            },
        )
        assert status == 400, body
        assert "invalid_top_logprobs" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_accepts_baseline_without_top_logprobs()
    test_http_completions_rejects_top_logprobs()
    test_http_completions_accepts_top_logprobs_zero_as_omit()
    test_http_completions_rejects_boolean_top_logprobs()
    print("ok")
