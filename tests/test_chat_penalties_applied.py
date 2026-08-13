"""Chat Completions presence/frequency penalties applied to ModelClient."""

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

_TEST_AUTH_TOKEN = "chat_penalties_applied_token"  # noqa: S105


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


def test_http_chat_applies_presence_and_frequency_penalties() -> None:
    orch = build()
    applied_p: list[float] = []
    applied_f: list[float] = []
    client = orch.client
    original_p = client.default_presence_penalty
    original_f = client.default_frequency_penalty

    class Tracker:
        def __init__(self, target: object) -> None:
            object.__setattr__(self, "_target", target)

        def __getattr__(self, name: str) -> object:
            return getattr(object.__getattribute__(self, "_target"), name)

        def __setattr__(self, name: str, value: object) -> None:
            if name == "default_presence_penalty" and isinstance(value, (int, float)):
                applied_p.append(float(value))
            if name == "default_frequency_penalty" and isinstance(value, (int, float)):
                applied_f.append(float(value))
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
                "presence_penalty": 0.4,
                "frequency_penalty": -0.3,
            },
        )
        assert status == 200, body
        assert 0.4 in applied_p, applied_p
        assert -0.3 in applied_f, applied_f
        assert client.default_presence_penalty == original_p
        assert client.default_frequency_penalty == original_f
    finally:
        server.shutdown()
        thread.join(timeout=5)
        orch.client = client


def test_http_chat_accepts_penalty_boundaries() -> None:
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
                "presence_penalty": 2,
                "frequency_penalty": -2,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_presence_penalty_out_of_range() -> None:
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
                "presence_penalty": 3,
            },
        )
        assert status == 400, body
        assert "invalid_presence_penalty" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_frequency_penalty_boolean() -> None:
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
                "frequency_penalty": False,
            },
        )
        assert status == 400, body
        assert "invalid_frequency_penalty" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_applies_presence_and_frequency_penalties()
    test_http_chat_accepts_penalty_boundaries()
    test_http_chat_rejects_presence_penalty_out_of_range()
    test_http_chat_rejects_frequency_penalty_boolean()
    print("ok")
