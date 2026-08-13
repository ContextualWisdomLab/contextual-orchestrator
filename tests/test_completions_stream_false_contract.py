"""Completions stream honesty: omit/false → 200; true/non-bool → 400."""

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

_TEST_AUTH_TOKEN = "completions_stream_false_contract_token"  # noqa: S105


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


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_completions_omits_stream_returns_text_completion() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello stream omit"},
        )
        assert status == 200, body
        assert body.get("object") == "text_completion" or "choices" in body
        # Non-SSE JSON body — not a stream framing.
        assert isinstance(body, dict)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_stream_false_returns_text_completion() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello stream false",
                "stream": False,
            },
        )
        assert status == 200, body
        assert "choices" in body
        choice0 = body["choices"][0]
        # text_completion choice shape (text field) rather than chat delta stream
        assert "text" in choice0 or "message" in choice0
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_stream_true_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello stream true",
                "stream": True,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream" in blob
        assert "chat/completions" in blob or "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_stream_non_boolean_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello stream string",
                "stream": "false",
            },
        )
        assert status == 400, body
        assert "invalid_stream" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_omits_stream_returns_text_completion()
    test_http_completions_stream_false_returns_text_completion()
    test_http_completions_stream_true_fail_closed()
    test_http_completions_stream_non_boolean_fail_closed()
    print("ok")
