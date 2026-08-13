"""Completions logit_bias rejected (not applied on route path)."""

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

_TEST_AUTH_TOKEN = "cmpl_lb_unsup_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_logit_bias_rejected() -> None:
    assert _validate_completions_logit_bias({}) is None
    try:
        _validate_completions_logit_bias({"logit_bias": {"50256": -100}})
        raise AssertionError("expected logit_bias reject")
    except RequestError as exc:
        assert exc.code == "invalid_logit_bias"
        assert "not supported" in exc.message


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


def test_http_accepts_without_logit_bias() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(port, {"model": "mock-generalist", "prompt": "hello"})
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_logit_bias() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello", "logit_bias": {"1": 10}},
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_logit_bias"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_logit_bias_rejected()
    test_http_accepts_without_logit_bias()
    test_http_rejects_logit_bias()
