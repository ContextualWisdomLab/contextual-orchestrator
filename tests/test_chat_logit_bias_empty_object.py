"""Chat/Completions logit_bias empty-object honesty (no-op accept)."""

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

_TEST_AUTH_TOKEN = "chat_logit_bias_empty_object_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


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


def test_http_chat_accepts_empty_logit_bias_object() -> None:
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
                "logit_bias": {},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_nonempty_logit_bias() -> None:
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
                "logit_bias": {"50256": -100},
            },
        )
        assert status == 400, body
        payload = json.dumps(body)
        assert "invalid_logit_bias" in payload
        assert "not supported" in payload
        assert "/v1/chat/completions" in payload
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_empty_logit_bias_object() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-generalist",
                "prompt": "hi",
                "logit_bias": {},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_nonempty_logit_bias() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-generalist",
                "prompt": "hi",
                "logit_bias": {"50256": 10},
            },
        )
        assert status == 400, body
        payload = json.dumps(body)
        assert "invalid_logit_bias" in payload
        assert "not supported" in payload
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_empty_logit_bias_object()
    test_http_chat_rejects_nonempty_logit_bias()
    test_http_completions_accepts_empty_logit_bias_object()
    test_http_completions_rejects_nonempty_logit_bias()
    print("ok")
