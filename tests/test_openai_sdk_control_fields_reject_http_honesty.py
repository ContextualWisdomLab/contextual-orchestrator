"""OpenAI SDK control fields (prompt_cache_key/safety_identifier/verbosity) reject honesty."""

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

_TEST_AUTH_TOKEN = "openai_sdk_control_fields_reject_http_honesty_token"  # noqa: S105


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


def test_http_chat_rejects_prompt_cache_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "cache key"}],
                "prompt_cache_key": "tenant-cache-1",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_prompt_cache_key" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_safety_identifier() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "safety id"}],
                "safety_identifier": "safety-abc",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_safety_identifier" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_verbosity() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "verbosity"}],
                "verbosity": "high",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_verbosity" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_prompt_cache_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "responses cache key",
                "prompt_cache_key": "resp-cache-1",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_prompt_cache_key" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_safety_identifier() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "completions safety",
                "safety_identifier": "comp-safety",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_safety_identifier" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_baseline_chat_without_sdk_controls() -> None:
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
