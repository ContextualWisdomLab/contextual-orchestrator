"""Completions logprobs must be false or an integer 0-5."""

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
    _validate_completions_logprobs,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_logprobs_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_completions_logprobs() -> None:
    assert _validate_completions_logprobs({}) is None
    assert _validate_completions_logprobs({"logprobs": False}) is False
    assert _validate_completions_logprobs({"logprobs": 0}) == 0
    assert _validate_completions_logprobs({"logprobs": 5}) == 5
    for bad in (True, 6, -1, "2", 1.5, None):
        try:
            _validate_completions_logprobs({"logprobs": bad})
            raise AssertionError(f"expected invalid_logprobs for {bad!r}")
        except RequestError as exc:
            assert exc.code == "invalid_logprobs"


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


def test_http_rejects_invalid_logprobs() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "logprobs": True},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_logprobs"

        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "logprobs": 6},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_logprobs"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_false_and_int_logprobs() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        for lp in (False, 0, 3, 5):
            status, body = _post(
                port,
                {"model": "mock-generalist", "prompt": "hello world", "logprobs": lp},
            )
            assert status == 200, (lp, body)
            assert body["object"] == "text_completion"
            assert body["choices"][0]["text"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_completions_logprobs()
    test_http_rejects_invalid_logprobs()
    test_http_accepts_false_and_int_logprobs()
