"""Completions store field honesty over HTTP (fail-closed)."""

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

_TEST_AUTH_TOKEN = "completions_store_http_honesty_token"  # noqa: S105


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


def test_http_completions_accepts_omitted_store() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port, {"model": "mock-planner", "prompt": "hello store omit"}
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_store_false() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "hello store false", "store": False},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_store_true() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "hello store true", "store": True},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_store" in blob
        assert "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_non_boolean_store() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "hello store bad", "store": "yes"},
        )
        assert status == 400, body
        assert "invalid_store" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_accepts_omitted_store()
    test_http_completions_accepts_store_false()
    test_http_completions_rejects_store_true()
    test_http_completions_rejects_non_boolean_store()
    print("ok")
