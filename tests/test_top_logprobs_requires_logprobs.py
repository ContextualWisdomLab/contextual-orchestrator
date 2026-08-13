"""top_logprobs requires logprobs=true (OpenAI contract)."""

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
    _validate_top_logprobs_requires_logprobs,
    build_server,
)

_TEST_AUTH_TOKEN = "top_lp_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_top_logprobs_requires_logprobs() -> None:
    _validate_top_logprobs_requires_logprobs({})
    _validate_top_logprobs_requires_logprobs({"logprobs": True, "top_logprobs": 5})
    _validate_top_logprobs_requires_logprobs({"logprobs": True})
    try:
        _validate_top_logprobs_requires_logprobs({"top_logprobs": 5})
        raise AssertionError("expected invalid_top_logprobs")
    except RequestError as exc:
        assert exc.code == "invalid_top_logprobs"
    try:
        _validate_top_logprobs_requires_logprobs({"logprobs": False, "top_logprobs": 3})
        raise AssertionError("expected invalid_top_logprobs")
    except RequestError as exc:
        assert exc.code == "invalid_top_logprobs"


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


def test_http_chat_rejects_top_logprobs_without_logprobs() -> None:
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
                "top_logprobs": 5,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_top_logprobs"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_top_logprobs_with_logprobs() -> None:
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
                "logprobs": True,
                "top_logprobs": 5,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_top_logprobs_requires_logprobs()
    test_http_chat_rejects_top_logprobs_without_logprobs()
    test_http_chat_accepts_top_logprobs_with_logprobs()
    print("ok")
