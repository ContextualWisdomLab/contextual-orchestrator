"""OpenAI background mode and Completions reasoning object reject honesty over HTTP."""

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

_TEST_AUTH_TOKEN = "background_reasoning_reject_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
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


def test_http_chat_rejects_background_true() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "background"}],
                "background": True,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_background" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_background_true() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "background responses",
                "background": True,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_background" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_reasoning_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "reasoning object",
                "reasoning": {"effort": "high"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_reasoning" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_baseline_without_background() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "baseline"}],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_background_false() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "background false"}],
                "background": False,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_background_false() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "background false responses",
                "background": False,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)
