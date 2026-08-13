"""max_tokens and max_completion_tokens are mutually exclusive."""

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
    _validate_max_tokens_exclusive,
    build_server,
)

_TEST_AUTH_TOKEN = "max_tok_excl_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_exclusive() -> None:
    _validate_max_tokens_exclusive({})
    _validate_max_tokens_exclusive({"max_tokens": 16})
    _validate_max_tokens_exclusive({"max_completion_tokens": 32})
    try:
        _validate_max_tokens_exclusive({"max_tokens": 16, "max_completion_tokens": 32})
        raise AssertionError("expected mutual exclusive reject")
    except RequestError as exc:
        assert exc.code == "invalid_max_tokens"


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


def test_http_chat_accepts_either_alone() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        for key, val in (("max_tokens", 16), ("max_completion_tokens", 24)):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-generalist",
                    "messages": [{"role": "user", "content": "hi"}],
                    key: val,
                },
            )
            assert status in {200, 202}, (key, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_both() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-generalist",
                "input": "hi",
                "max_tokens": 10,
                "max_completion_tokens": 20,
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_max_tokens"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_exclusive()
    test_http_chat_accepts_either_alone()
    test_http_responses_rejects_both()
    print("ok")
