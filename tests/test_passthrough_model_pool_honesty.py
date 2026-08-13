"""Passthrough model pool honesty: unknown model fails closed; known model routes."""

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

_TEST_AUTH_TOKEN = "passthrough_model_pool_honesty_token"  # noqa: S105

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_invoice",
            "description": "Look up an invoice",
            "parameters": {
                "type": "object",
                "properties": {"invoice_id": {"type": "string"}},
                "required": ["invoice_id"],
            },
        },
    }
]


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent(
                "general_agent",
                "mock-generalist",
                tags=("reasoning", "writing"),
            )
        ]
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


def test_http_chat_passthrough_rejects_unknown_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "gpt-4o-not-in-pool",
                "messages": [{"role": "user", "content": "lookup invoice 7"}],
                "tools": _TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "not available" in blob or "invalid_request" in blob
        assert "gpt-4o-not-in-pool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_passthrough_accepts_pool_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "lookup invoice 7"}],
                "tools": _TOOLS,
            },
        )
        assert status == 200, body
        # mock echoes model
        assert body.get("model") == "mock-generalist" or "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_unknown_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "o3-pro-not-in-pool",
                "input": "draft a payment plan",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "not available" in blob or "invalid_request" in blob
        assert "o3-pro-not-in-pool" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_pool_model() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-generalist",
                "input": "draft a payment plan",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_passthrough_rejects_unknown_model()
    test_http_chat_passthrough_accepts_pool_model()
    test_http_responses_rejects_unknown_model()
    test_http_responses_accepts_pool_model()
    print("ok")
