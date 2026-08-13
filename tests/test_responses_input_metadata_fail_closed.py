"""Responses API: require input; OpenAI metadata shape; stream honesty."""

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

_TEST_AUTH_TOKEN = "responses_input_metadata_fail_closed_token"  # noqa: S105


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


def test_http_responses_accepts_string_input() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "input": "summarize this note"},
        )
        assert status == 200, body
        assert body.get("object") == "response" or "output" in body or "id" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_missing_input() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "mock-generalist"})
        assert status == 400, body
        assert "invalid_input" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_empty_input() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "mock-generalist", "input": "   "})
        assert status == 400, body
        assert "invalid_input" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_bad_metadata() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "ok",
                "metadata": {"count": 3},
            },
        )
        assert status == 400, body
        assert "invalid_metadata" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_string_metadata() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "ok",
                "metadata": {"request_id": "r1"},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_stream_true_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "input": "ok", "stream": True},
        )
        assert status == 400, body
        assert "invalid_stream" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_accepts_string_input()
    test_http_responses_rejects_missing_input()
    test_http_responses_rejects_empty_input()
    test_http_responses_rejects_bad_metadata()
    test_http_responses_accepts_string_metadata()
    test_http_responses_stream_true_fail_closed()
    print("ok")
