"""OpenAI prompt_cache_key and safety_identifier accept + shape validation."""

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
    _validate_prompt_cache_key,
    _validate_safety_identifier,
    build_server,
)

_TEST_AUTH_TOKEN = "prompt_cache_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_prompt_cache_and_safety() -> None:
    assert _validate_prompt_cache_key({}) is None
    assert _validate_prompt_cache_key({"prompt_cache_key": "sess-1"}) == "sess-1"
    try:
        _validate_prompt_cache_key({"prompt_cache_key": ""})
        raise AssertionError("empty")
    except RequestError as exc:
        assert exc.code == "invalid_prompt_cache_key"
    try:
        _validate_prompt_cache_key({"prompt_cache_key": "x" * 65})
        raise AssertionError("long")
    except RequestError as exc:
        assert exc.code == "invalid_prompt_cache_key"
    assert _validate_safety_identifier({"safety_identifier": "end-user-9"}) == "end-user-9"
    try:
        _validate_safety_identifier({"safety_identifier": "  "})
        raise AssertionError("blank")
    except RequestError as exc:
        assert exc.code == "invalid_safety_identifier"


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


def test_http_chat_accepts_prompt_cache_and_safety() -> None:
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
                "prompt_cache_key": "cache-a",
                "safety_identifier": "buyer-42",
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_blank_safety_identifier() -> None:
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
                "safety_identifier": "",
            },
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_safety_identifier"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_prompt_cache_key() -> None:
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
                "input": "hello",
                "prompt_cache_key": "resp-cache",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_prompt_cache_and_safety()
    test_http_chat_accepts_prompt_cache_and_safety()
    test_http_chat_rejects_blank_safety_identifier()
    test_http_responses_accepts_prompt_cache_key()
    print("ok")
