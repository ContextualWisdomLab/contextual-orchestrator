"""service_tier casefold omit + routing null optional omit over HTTP."""

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

_TEST_AUTH_TOKEN = "service_tier_routing_null_omit_http_honesty_token"  # noqa: S105


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
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_service_tier_auto_default_padded_casefold() -> None:
    server, thread, port = _server()
    try:
        for value in ("auto", "default", " AUTO ", " Default ", "AuTo"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "tier"}],
                    "service_tier": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_service_tier_flex() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tier flex"}],
                "service_tier": "flex",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_service_tier" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_routing_null_optional_fields() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "routing nulls"}],
                "routing": {
                    "channel": None,
                    "latency_tolerant": None,
                    "priority": None,
                },
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_routing_padded_channel_and_priority() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "routing pad"}],
                "routing": {
                    "channel": " SYNC ",
                    "latency_tolerant": False,
                    "priority": " Normal ",
                },
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_routing_latency_non_boolean() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "routing bad"}],
                "routing": {"latency_tolerant": "yes"},
            },
        )
        assert status == 400, body
        assert "invalid_routing" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_service_tier_auto_default_padded_casefold()
    test_http_chat_rejects_service_tier_flex()
    test_http_chat_accepts_routing_null_optional_fields()
    test_http_chat_accepts_routing_padded_channel_and_priority()
    test_http_chat_rejects_routing_latency_non_boolean()
    print("ok")
