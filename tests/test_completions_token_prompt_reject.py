"""Completions token-id prompt arrays are rejected with a clear invalid_prompt."""

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
    _validate_completion_prompt,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_token_prompt_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_rejects_token_id_prompts() -> None:
    try:
        _validate_completion_prompt([1, 2, 3, 4])
        raise AssertionError("expected token-id reject")
    except RequestError as exc:
        assert exc.code == "invalid_prompt"
        assert "token-id" in exc.message

    try:
        _validate_completion_prompt([[1, 2], [3, 4]])
        raise AssertionError("expected nested token-id reject")
    except RequestError as exc:
        assert exc.code == "invalid_prompt"
        assert "token-id" in exc.message

    # String and string-array forms remain accepted.
    assert _validate_completion_prompt("hello")[0]["content"] == "hello"
    assert _validate_completion_prompt(["a", "b"])[0]["content"] == "a\nb"


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


def test_http_rejects_token_id_prompt() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": [15496, 11, 995]},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_prompt"
        assert "token-id" in body["error"]["message"]

        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": [[15496], [11, 995]]},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_prompt"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_string_prompt() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "Hello, world"},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert body["choices"][0]["text"]

        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": ["line one", "line two"]},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_rejects_token_id_prompts()
    test_http_rejects_token_id_prompt()
    test_http_accepts_string_prompt()
