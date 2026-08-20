"""include_orchestration_trace null is rejected over HTTP."""

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

_TEST_AUTH_TOKEN = "include_orchestration_trace_null_noop_http_honesty_token"  # noqa: S105


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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_rejects_include_orchestration_trace_null() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "trace null omit"}],
                "include_orchestration_trace": None,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_include_orchestration_trace"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_non_boolean_include_orchestration_trace() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "trace bad"}],
                "include_orchestration_trace": "yes",
            },
        )
        assert status == 400, body
        assert "invalid_include_orchestration_trace" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_accepts_include_orchestration_trace_true_false() -> None:
    server, thread, port = _server()
    try:
        for val in (True, False):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"trace {val}"}],
                    "include_orchestration_trace": val,
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)
