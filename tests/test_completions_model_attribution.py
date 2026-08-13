"""Completions model maps to cost-ledger model_name when attribution unset."""

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

_TEST_AUTH_TOKEN = "cmpl_model_attr_token"  # noqa: S105


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


def test_http_model_maps_to_model_name() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "bill me"},
        )
        assert status == 200, body
        items = _records(port)
        assert any(
            (row.get("model_name") == "mock-generalist")
            for row in items
        ), items
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_explicit_model_name_wins() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "bill me",
                "attribution": {"model_name": "explicit-model"},
            },
        )
        assert status == 200, body
        items = _records(port)
        assert any(row.get("model_name") == "explicit-model" for row in items), items
        assert not any(
            row.get("model_name") == "mock-generalist" and row.get("model_name") != "explicit-model"
            for row in items
            if row.get("model_name") == "mock-generalist"
        )
        # Explicit must appear; request model must not override it.
        models = [row.get("model_name") for row in items]
        assert "explicit-model" in models
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_user_and_model_both_map() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "x", "user": "tenant-9"},
        )
        assert status == 200, body
        items = _records(port)
        assert any(
            row.get("account_name") == "tenant-9" and row.get("model_name") == "mock-generalist"
            for row in items
        ), items
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_model_maps_to_model_name()
    test_http_explicit_model_name_wins()
    test_http_user_and_model_both_map()
