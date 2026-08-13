"""Routing hints: typed fields + free-form cost_preference validation."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.batch_routing import RoutingHints  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _validate_routing,
    build_server,
)

_TEST_AUTH_TOKEN = "routing_pref_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_routing_cost_preference() -> None:
    assert _validate_routing(None) is None
    good = {
        "channel": "sync",
        "latency_tolerant": False,
        "priority": "interactive",
        "cost_preference": "free_first",
    }
    assert _validate_routing(good) == good
    for bad in (
        {"latency_tolerant": "yes"},
        {"priority": "urgent"},
        {"cost_preference": "max_speed"},
        {"unknown_key": 1},
    ):
        try:
            _validate_routing(bad)
            raise AssertionError(f"expected reject for {bad!r}")
        except RequestError as exc:
            assert exc.code == "invalid_routing"


def test_routing_hints_carries_cost_preference() -> None:
    hints = RoutingHints.from_mapping({"cost_preference": "cheapest", "priority": "bulk"})
    assert hints.cost_preference == "cheapest"
    assert hints.priority == "bulk"


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


def test_http_chat_accepts_cost_preference() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "routing": {"cost_preference": "free_first", "priority": "normal"},
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_bad_cost_preference() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "routing": {"cost_preference": "max_speed"},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_routing"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_routing_cost_preference()
    test_routing_hints_carries_cost_preference()
    test_http_chat_accepts_cost_preference()
    test_http_chat_rejects_bad_cost_preference()
    print("ok")
