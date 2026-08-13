"""Chat max_completion_tokens wins over max_tokens for provider budget."""

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

_TEST_AUTH_TOKEN = "chat_max_completion_prec_token"  # noqa: S105


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


def test_http_chat_accepts_max_completion_tokens() -> None:
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
                "messages": [{"role": "user", "content": "hi"}],
                "max_completion_tokens": 64,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_max_completion_tokens_overrides_max_tokens() -> None:
    """When both set, max_completion_tokens is the applied budget (OpenAI precedence)."""
    orch = build()
    applied: list[int] = []
    client = orch.client
    original = client.max_output_tokens

    def tracking_setattr(name: str, value: object) -> None:
        if name == "max_output_tokens" and isinstance(value, int):
            applied.append(value)
        object.__setattr__(client, name, value)

    # Track assignments during the request by wrapping __setattr__ is heavy;
    # observe via a temporary property-like hook on the instance dict path.
    class Tracker:
        def __init__(self, target: object) -> None:
            object.__setattr__(self, "_target", target)
            object.__setattr__(self, "_applied", applied)

        def __getattr__(self, name: str) -> object:
            return getattr(object.__getattribute__(self, "_target"), name)

        def __setattr__(self, name: str, value: object) -> None:
            if name == "max_output_tokens" and isinstance(value, int):
                object.__getattribute__(self, "_applied").append(value)
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
                "max_tokens": 10,
                "max_completion_tokens": 77,
            },
        )
        assert status == 200, body
        # Applied budget should include 77 (max_completion_tokens), not only 10
        assert 77 in applied, applied
        # Restored after request
        assert client.max_output_tokens == original
    finally:
        server.shutdown()
        thread.join(timeout=5)
        orch.client = client


def test_http_chat_rejects_invalid_max_completion_tokens() -> None:
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
                "max_completion_tokens": 0,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_max_completion_tokens"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_integer_max_completion_tokens() -> None:
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
                "max_completion_tokens": 1.5,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_max_completion_tokens"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_max_completion_tokens()
    test_http_chat_max_completion_tokens_overrides_max_tokens()
    test_http_chat_rejects_invalid_max_completion_tokens()
    test_http_chat_rejects_non_integer_max_completion_tokens()
