"""Chat Completions top_p applied to ModelClient; range fail-closed."""

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

_TEST_AUTH_TOKEN = "chat_top_p_applied_token"  # noqa: S105


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


def test_http_chat_applies_top_p_to_client() -> None:
    orch = build()
    applied: list[float] = []
    client = orch.client
    original = client.default_top_p

    class Tracker:
        def __init__(self, target: object) -> None:
            object.__setattr__(self, "_target", target)

        def __getattr__(self, name: str) -> object:
            return getattr(object.__getattribute__(self, "_target"), name)

        def __setattr__(self, name: str, value: object) -> None:
            if name == "default_top_p" and isinstance(value, (int, float)):
                applied.append(float(value))
            setattr(object.__getattribute__(self, "_target"), name, value)

    orch.client = Tracker(client)  # type: ignore[assignment]
    server = build_server(orch, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "top_p": 0.65,
            },
        )
        assert status == 200, body
        assert 0.65 in applied, applied
        assert client.default_top_p == original
    finally:
        server.shutdown()
        thread.join(timeout=5)
        orch.client = client


def test_http_chat_accepts_top_p_one() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "top_p": 1,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_top_p_zero() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "top_p": 0,
            },
        )
        assert status == 400, body
        assert "invalid_top_p" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_top_p_above_one() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "top_p": 1.01,
            },
        )
        assert status == 400, body
        assert "invalid_top_p" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_applies_top_p_to_client()
    test_http_chat_accepts_top_p_one()
    test_http_chat_rejects_top_p_zero()
    test_http_chat_rejects_top_p_above_one()
    print("ok")
