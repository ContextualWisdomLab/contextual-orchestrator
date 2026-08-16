"""Live HTTP: mixed mode aliases must not hide a Conductor workflow.

A buyer who sends ``orchestration=route`` plus ``mode=conduct`` asked for a
Conductor workflow (Nielsen et al., 2025). The first-wins ``or`` chain billed a
Fugu-style single-worker route instead. Each alias is checked on its own.
"""

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

_TEST_AUTH_TOKEN = "chat_orchestration_mode_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "writing")),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "review")),
        ]
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
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server() -> tuple[object, threading.Thread, int]:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_rejects_mixed_route_and_conduct_aliases() -> None:
    """``orchestration=route`` must not hide ``mode=conduct`` on the chat path."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "analyze, implement, and verify the invoice parser"}],
                "orchestration": "route",
                "mode": "conduct",
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_mode"
        assert "agree" in body["error"]["message"]
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_mixed_route_and_whitespace_mode() -> None:
    """``orchestration=route`` must not hide whitespace-only ``mode``."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "say hi"}],
                "orchestration": "route",
                "mode": "   ",
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_mode"
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_agreeing_route_aliases() -> None:
    """The same value on two aliases is an honest no-op, not a conflict."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "say hi"}],
                "orchestration": "route",
                "mode": "route",
            },
        )
        assert status == 200, body
        assert body["orchestration"]["mode"] == "route"
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_empty_string_mode_as_omit() -> None:
    """JSON empty-string mode stays omit-equivalent; spaces do not."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "say hi"}],
                "orchestration": "route",
                "mode": "",
            },
        )
        assert status == 200, body
        assert body["orchestration"]["mode"] == "route"
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_null_mode_as_omit() -> None:
    """JSON null mode stays omit-equivalent."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "say hi"}],
                "mode": None,
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_mode_conduct() -> None:
    """A single ``mode=conduct`` still runs the Conductor workflow."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "analyze, implement, and verify the invoice parser"}],
                "mode": "conduct",
            },
        )
        assert status == 200, body
        assert body["orchestration"]["mode"] == "conduct"
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_rejects_mixed_route_and_conduct_aliases()
    test_http_chat_rejects_mixed_route_and_whitespace_mode()
    test_http_chat_accepts_agreeing_route_aliases()
    test_http_chat_accepts_empty_string_mode_as_omit()
    test_http_chat_accepts_null_mode_as_omit()
    test_http_chat_accepts_mode_conduct()
    print("ok")
