"""Responses API reasoning: fail-closed when present (not applied on passthrough)."""

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

_TEST_AUTH_TOKEN = "responses_reasoning_fail_closed_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/responses",
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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_responses_omits_reasoning_succeeds() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "input": "plain response request"},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_reasoning_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "needs deep thinking",
                "reasoning": {"effort": "high"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_reasoning" in blob
        assert "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_reasoning_null() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "input": "x", "reasoning": None},
        )
        assert status == 400, body
        assert "invalid_reasoning" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_reasoning_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "input": "x", "reasoning": "high"},
        )
        assert status == 400, body
        assert "invalid_reasoning" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_omits_reasoning_succeeds()
    test_http_responses_rejects_reasoning_object()
    test_http_responses_rejects_reasoning_null()
    test_http_responses_rejects_reasoning_string()
    print("ok")
