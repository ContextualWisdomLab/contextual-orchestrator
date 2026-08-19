"""Responses API service_tier honesty over HTTP (fail-closed)."""

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

_TEST_AUTH_TOKEN = "responses_service_tier_http_honesty_token"  # noqa: S105


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


def test_http_responses_accepts_omitted_service_tier() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "mock-planner", "input": "hello tier omit"})
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_auto_and_default_service_tier() -> None:
    server, thread, port = _server()
    try:
        for tier in ("auto", "default"):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "input": f"hello tier {tier}",
                    "service_tier": tier,
                },
            )
            assert status == 200, (tier, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_flex_service_tier() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello tier flex",
                "service_tier": "flex",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_priority_service_tier() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello tier priority",
                "service_tier": "priority",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_non_string_service_tier() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello tier bad",
                "service_tier": 1,
            },
        )
        assert status == 400, body
        assert "invalid_service_tier" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_accepts_omitted_service_tier()
    test_http_responses_accepts_auto_and_default_service_tier()
    test_http_responses_accepts_flex_service_tier()
    test_http_responses_accepts_priority_service_tier()
    test_http_responses_rejects_non_string_service_tier()
    print("ok")
