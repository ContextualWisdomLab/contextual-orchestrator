"""Responses conversation-control fields honesty over HTTP (fail-closed)."""

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

_TEST_AUTH_TOKEN = "responses_conversation_controls_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
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
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_responses_accepts_baseline_without_conversation_controls() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port, {"model": "mock-planner", "input": "hello baseline"}
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_previous_response_id() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello prev",
                "previous_response_id": "resp_abc123",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_previous_response_id" in blob
        assert "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_conversation() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello conversation",
                "conversation": "conv_abc",
            },
        )
        assert status == 400, body
        assert "invalid_conversation" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_truncation() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello truncation",
                "truncation": "auto",
            },
        )
        assert status == 400, body
        assert "invalid_truncation" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_include() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello include",
                "include": ["file_search_call.results"],
            },
        )
        assert status == 400, body
        assert "invalid_include" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_text_control() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello text control",
                "text": {"format": {"type": "text"}},
            },
        )
        assert status == 400, body
        assert "invalid_text" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_accepts_baseline_without_conversation_controls()
    test_http_responses_rejects_previous_response_id()
    test_http_responses_rejects_conversation()
    test_http_responses_rejects_truncation()
    test_http_responses_rejects_include()
    test_http_responses_rejects_text_control()
    print("ok")
