"""Chat Completions reasoning_effort honesty over HTTP (not applied on route path)."""

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

_TEST_AUTH_TOKEN = "chat_reasoning_effort_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
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


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_reasoning_effort_known_levels() -> None:
    """Known o-series levels are default-effort no-ops (no effort plane)."""
    server, thread, port = _server()
    try:
        for effort in ("low", "MEDIUM", " High ", "high", "minimal", "none"):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"think {effort!r}"}],
                    "reasoning_effort": effort,
                },
            )
            assert status == 200, (effort, body)
            assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_unknown_reasoning_effort() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "think max"}],
                "reasoning_effort": "max",
            },
        )
        assert status == 400, body
        assert "invalid_reasoning_effort" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_reasoning_effort_none_as_omit() -> None:
    """OpenAI none disables extra reasoning — honest omit no-op on this gateway."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "think none"}],
                "reasoning_effort": "none",
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_orchestrator_auto_without_provider_forwarding() -> None:
    """Consumer default ``auto`` stays at the orchestration boundary."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "synthetic auto effort"}],
                "reasoning_effort": "auto",
            },
        )
        assert status == 200, body
        assert "choices" in body
        assert "reasoning_effort" not in body.get("echo", {})
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_reasoning_effort_bool() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "think bool"}],
                "reasoning_effort": True,
            },
        )
        assert status == 400, body
        assert "invalid_reasoning_effort" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_reasoning_effort_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "no reasoning knob"}],
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_reasoning_effort_known_levels()
    test_http_chat_still_rejects_unknown_reasoning_effort()
    test_http_chat_accepts_reasoning_effort_none_as_omit()
    test_http_chat_rejects_reasoning_effort_bool()
    test_http_chat_accepts_reasoning_effort_omitted()
    print("ok")
