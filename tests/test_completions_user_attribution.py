"""Completions user maps to cost-ledger account attribution when unset."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    SecurityConfig,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_user_attr_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
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


def test_http_user_maps_to_account() -> None:
    orch = build()
    server = build_server(orch, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "user": "end-user-42"},
        )
        assert status == 200, body
        # Coordinator attaches usage_record_id; ledger should hold account.
        usage_id = body.get("usage_record_id")
        # usage may be nested; also check ledger via coordinator path
        # Poll ledger records for account_name
        from contextual_orchestrator.server import build_server as _  # noqa: F401
    finally:
        server.shutdown()
        thread.join(timeout=5)
    # Re-run with ledger access through coordinator on a new server
    orch2 = build()
    server2 = build_server(orch2, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread2 = threading.Thread(target=server2.serve_forever, daemon=True)
    thread2.start()
    port2 = server2.server_address[1]
    try:
        status, body = _post(
            port2,
            {"model": "mock-generalist", "prompt": "hello", "user": "end-user-42"},
        )
        assert status == 200, body
        # Access coordinator ledger via build_server default - use API cost records
        req = urllib.request.Request(
            f"http://127.0.0.1:{port2}/api/v1/llm_usage_records",
            headers={"authorization": f"Bearer {_TEST_AUTH_TOKEN}", "connection": "close"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = payload.get("items") or payload.get("records") or payload
        if isinstance(items, dict):
            items = items.get("items") or []
        assert any(
            (row.get("account_name") or row.get("account")) == "end-user-42"
            for row in items
        ), payload
    finally:
        server2.shutdown()
        thread2.join(timeout=5)


def test_http_explicit_attribution_account_wins() -> None:
    orch = build()
    server = build_server(orch, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello",
                "user": "from-user",
                "attribution": {"account": "explicit-account"},
            },
        )
        assert status == 200, body
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
        assert any(
            (row.get("account_name") or row.get("account")) == "explicit-account"
            for row in items
        ), payload
        assert not any(
            (row.get("account_name") or row.get("account")) == "from-user"
            for row in items
        ), payload
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_empty_user() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "user": "  "},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_user"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_user_maps_to_account()
    test_http_explicit_attribution_account_wins()
    test_http_rejects_empty_user()
