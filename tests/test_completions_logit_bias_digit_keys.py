"""Completions logit_bias keys must be digit token ids."""

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
    _validate_completions_logit_bias,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_logit_digit_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_logit_bias_digit_keys() -> None:
    assert _validate_completions_logit_bias({"logit_bias": {"50256": -100}}) == {"50256": -100.0}
    assert _validate_completions_logit_bias({"logit_bias": {42: 10}}) == {"42": 10.0}
    try:
        _validate_completions_logit_bias({"logit_bias": {"eos": -100}})
        raise AssertionError("expected non-digit key rejection")
    except RequestError as exc:
        assert exc.code == "invalid_logit_bias"
    try:
        _validate_completions_logit_bias({"logit_bias": {"": 1}})
        raise AssertionError("expected empty key rejection")
    except RequestError as exc:
        assert exc.code == "invalid_logit_bias"
    try:
        _validate_completions_logit_bias({"logit_bias": {"12a": 1}})
        raise AssertionError("expected mixed key rejection")
    except RequestError as exc:
        assert exc.code == "invalid_logit_bias"


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


def test_http_rejects_non_digit_logit_bias_key() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello",
                "logit_bias": {"not-a-token": -50},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_logit_bias"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_digit_logit_bias_keys() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello world",
                "logit_bias": {"50256": -100, "0": 5},
            },
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_logit_bias_digit_keys()
    test_http_rejects_non_digit_logit_bias_key()
    test_http_accepts_digit_logit_bias_keys()
