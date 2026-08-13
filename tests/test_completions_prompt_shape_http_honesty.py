"""Legacy Completions prompt shape honesty over HTTP."""

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

_TEST_AUTH_TOKEN = "completions_prompt_shape_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_completions_accepts_string_prompt() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "mock-planner", "prompt": "hello buyer"})
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_string_array_prompt() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": ["line one", "line two"]},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_empty_string_prompt() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "mock-planner", "prompt": "   "})
        assert status == 400, body
        assert "invalid_prompt" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_empty_array_prompt() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "mock-planner", "prompt": []})
        assert status == 400, body
        assert "invalid_prompt" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_blank_array_item() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": ["ok", "  "]},
        )
        assert status == 400, body
        assert "invalid_prompt" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_missing_prompt() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "mock-planner"})
        assert status == 400, body
    finally:
        server.shutdown()
        thread.join(timeout=5)
