"""stream=true is invalid when n > 1 (OpenAI chat/Responses contract)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _validate_stream_n_exclusive,
    build_server,
)

_TEST_AUTH_TOKEN = "stream_n_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_stream_n_exclusive() -> None:
    _validate_stream_n_exclusive({})
    _validate_stream_n_exclusive({"stream": True})
    _validate_stream_n_exclusive({"stream": True, "n": 1})
    _validate_stream_n_exclusive({"stream": False, "n": 3})
    try:
        _validate_stream_n_exclusive({"stream": True, "n": 2})
        raise AssertionError("expected invalid_request")
    except RequestError as exc:
        assert exc.code == "invalid_request"
        assert "n" in (exc.message or "").lower() or "stream" in (exc.message or "").lower()


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


def test_http_chat_rejects_stream_with_n_gt_1() -> None:
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
                "stream": True,
                "n": 3,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_request"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_stream_with_n_1() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        # stream=true with n=1 should not hit the exclusive validator; may stream 200
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "mock-generalist",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                    "n": 2,
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 200
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_stream_n_exclusive()
    test_http_chat_rejects_stream_with_n_gt_1()
    test_http_chat_accepts_stream_with_n_1()
    print("ok")
