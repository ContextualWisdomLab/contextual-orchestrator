"""OpenAI logit_bias map validation on chat completions."""

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
    _validate_logit_bias,
    build_server,
)

_TEST_AUTH_TOKEN = "logit_bias_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_logit_bias() -> None:
    assert _validate_logit_bias({}) is None
    assert _validate_logit_bias({"logit_bias": {"50256": -100, "220": 50.5}}) == {
        "50256": -100.0,
        "220": 50.5,
    }
    assert _validate_logit_bias({"logit_bias": {}}) == {}
    try:
        _validate_logit_bias({"logit_bias": "nope"})
        raise AssertionError("expected non-object reject")
    except RequestError as exc:
        assert exc.code == "invalid_logit_bias"
    try:
        _validate_logit_bias({"logit_bias": {"50256": "ban"}})
        raise AssertionError("expected non-number reject")
    except RequestError as exc:
        assert exc.code == "invalid_logit_bias"
    try:
        _validate_logit_bias({"logit_bias": {"50256": 101}})
        raise AssertionError("expected range reject")
    except RequestError as exc:
        assert exc.code == "invalid_logit_bias"
    try:
        _validate_logit_bias({"logit_bias": {"50256": True}})
        raise AssertionError("expected bool reject")
    except RequestError as exc:
        assert exc.code == "invalid_logit_bias"


def test_http_logit_bias_accepted() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "orchestration": "route",
                    "logit_bias": {"50256": -100},
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert body["object"] == "chat.completion"


def test_http_logit_bias_out_of_range_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "logit_bias": {"50256": 200},
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert body["error"]["code"] == "invalid_logit_bias"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_logit_bias()
    test_http_logit_bias_accepted()
    test_http_logit_bias_out_of_range_rejected()
    print("ok")
