"""service_tier flex/priority accepted as default-capacity no-ops over HTTP."""

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

_TEST_AUTH_TOKEN = "service_tier_flex_priority_noop_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=10) as response:
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


def test_http_surfaces_accept_flex_priority_casefold() -> None:
    server, thread, port = _server()
    try:
        for path, payload_key, payload_val in (
            ("/v1/chat/completions", "messages", [{"role": "user", "content": "hi"}]),
            ("/v1/completions", "prompt", "hi"),
            ("/v1/responses", "input", "hi"),
        ):
            for tier in ("flex", "FLEX", " flex ", "priority", "PRIORITY", " Priority "):
                body = {"model": "mock-planner", "service_tier": tier, payload_key: payload_val}
                status, resp = _post(port, path, body)
                assert status == 200, (path, tier, resp)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_unknown_service_tier() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "scale"}],
                "service_tier": "scale",
            },
        )
        assert status == 400, body
        assert "invalid_service_tier" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_surfaces_accept_flex_priority_casefold()
    test_http_chat_still_rejects_unknown_service_tier()
    print("ok")
