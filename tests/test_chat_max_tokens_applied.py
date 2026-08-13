"""Chat max_tokens / max_completion_tokens applied to ModelClient; invalid fail-closed."""

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

_TEST_AUTH_TOKEN = "chat_max_tokens_applied_token"  # noqa: S105


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


def test_http_chat_applies_max_tokens_to_client() -> None:
    orch = build()
    applied: list[int] = []
    client = orch.client
    original = client.max_output_tokens

    class Tracker:
        def __init__(self, target: object) -> None:
            object.__setattr__(self, "_target", target)

        def __getattr__(self, name: str) -> object:
            return getattr(object.__getattribute__(self, "_target"), name)

        def __setattr__(self, name: str, value: object) -> None:
            if name == "max_output_tokens" and isinstance(value, int):
                applied.append(value)
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
                "max_tokens": 55,
            },
        )
        assert status == 200, body
        assert 55 in applied, applied
        assert client.max_output_tokens == original
    finally:
        server.shutdown()
        thread.join(timeout=5)
        orch.client = client


def test_http_chat_applies_max_completion_tokens_alone() -> None:
    orch = build()
    applied: list[int] = []
    client = orch.client

    class Tracker:
        def __init__(self, target: object) -> None:
            object.__setattr__(self, "_target", target)

        def __getattr__(self, name: str) -> object:
            return getattr(object.__getattribute__(self, "_target"), name)

        def __setattr__(self, name: str, value: object) -> None:
            if name == "max_output_tokens" and isinstance(value, int):
                applied.append(value)
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
                "max_completion_tokens": 91,
            },
        )
        assert status == 200, body
        assert 91 in applied, applied
    finally:
        server.shutdown()
        thread.join(timeout=5)
        orch.client = client


def test_http_chat_rejects_max_tokens_zero() -> None:
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
                "max_tokens": 0,
            },
        )
        assert status == 400, body
        assert "invalid_max_tokens" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_max_completion_tokens_boolean() -> None:
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
                "max_completion_tokens": True,
            },
        )
        assert status == 400, body
        assert "invalid_max_completion_tokens" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_applies_max_tokens_to_client()
    test_http_chat_applies_max_completion_tokens_alone()
    test_http_chat_rejects_max_tokens_zero()
    test_http_chat_rejects_max_completion_tokens_boolean()
    print("ok")
