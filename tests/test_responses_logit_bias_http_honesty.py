"""Responses logit_bias shape honesty over HTTP (fail-closed; valid maps passthrough)."""

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

_TEST_AUTH_TOKEN = "responses_logit_bias_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_responses_accepts_omitted_logit_bias() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, {"model": "mock-planner", "input": "hello omit bias"})
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_empty_logit_bias() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "input": "hello empty bias", "logit_bias": {}},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_valid_logit_bias_map() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello valid bias",
                "logit_bias": {"42": 10.0, "7": -5},
            },
        )
        assert status == 200, body
        echo = body.get("echo", {})
        assert echo.get("logit_bias") == {"42": 10.0, "7": -5}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_non_object_logit_bias() -> None:
    server, thread, port = _server()
    try:
        for bad in ("nope", [1, 2], 12, True):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "input": "bad bias type",
                    "logit_bias": bad,
                },
            )
            assert status == 400, (bad, body)
            assert "invalid_logit_bias" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_non_digit_logit_bias_keys() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "bad bias key",
                "logit_bias": {"token-a": 1.0},
            },
        )
        assert status == 400, body
        assert "invalid_logit_bias" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_out_of_range_logit_bias_values() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "bad bias value",
                "logit_bias": {"1": 101},
            },
        )
        assert status == 400, body
        assert "invalid_logit_bias" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_accepts_omitted_logit_bias()
    test_http_responses_accepts_empty_logit_bias()
    test_http_responses_accepts_valid_logit_bias_map()
    test_http_responses_rejects_non_object_logit_bias()
    test_http_responses_rejects_non_digit_logit_bias_keys()
    test_http_responses_rejects_out_of_range_logit_bias_values()
    print("ok")
