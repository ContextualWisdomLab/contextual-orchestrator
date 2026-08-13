"""Chat completions maps user/model/service into cost-ledger attribution."""

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

_TEST_AUTH_TOKEN = "chat_attr_parity_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
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


def _records(port: int) -> list:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/llm_usage_records",
        headers={"authorization": f"Bearer {_TEST_AUTH_TOKEN}", "connection": "close"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    items = payload.get("items") or payload.get("records") or payload
    if isinstance(items, dict):
        items = items.get("items") or []
    return items


def test_http_chat_user_model_service_attribution() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hello"}],
                "user": "chat-tenant-1",
            },
        )
        assert status == 200, body
        assert body["object"] == "chat.completion"
        items = _records(port)
        assert any(
            row.get("account_name") == "chat-tenant-1"
            and row.get("model_name") == "mock-generalist"
            and row.get("service_name") == "chat_completions_api"
            for row in items
        ), items
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_explicit_attribution_wins() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hello"}],
                "user": "ignored-user",
                "attribution": {
                    "account": "explicit-acct",
                    "service": "explicit-svc",
                    "model_name": "explicit-model",
                },
            },
        )
        assert status == 200, body
        items = _records(port)
        assert any(
            row.get("account_name") == "explicit-acct"
            and row.get("service_name") == "explicit-svc"
            and row.get("model_name") == "explicit-model"
            for row in items
        ), items
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_string_user() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hello"}],
                "user": 123,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_user"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_user_model_service_attribution()
    test_http_chat_explicit_attribution_wins()
    test_http_chat_rejects_non_string_user()
