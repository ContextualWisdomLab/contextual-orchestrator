"""Responses logit_bias and logprobs shape honesty over HTTP (fail-closed)."""

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

_TEST_AUTH_TOKEN = "responses_logit_bias_logprobs_http_honesty_token"  # noqa: S105


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


def test_http_responses_accepts_empty_and_valid_logit_bias() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "input": "bias empty", "logit_bias": {}},
        )
        assert status == 200, body
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "bias map",
                "logit_bias": {"50256": -100, "220": 50},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_non_digit_logit_bias_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "bias bad key",
                "logit_bias": {"not-a-token": 1},
            },
        )
        assert status == 400, body
        assert "invalid_logit_bias" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_out_of_range_logit_bias_value() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "bias bad value",
                "logit_bias": {"100": 101},
            },
        )
        assert status == 400, body
        assert "invalid_logit_bias" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_logprobs_false() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "input": "lp false", "logprobs": False},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_logprobs_true_with_top_logprobs() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "lp true",
                "logprobs": True,
                "top_logprobs": 5,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_top_logprobs_without_logprobs() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "input": "tlp alone", "top_logprobs": 5},
        )
        assert status == 400, body
        assert "invalid_top_logprobs" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_non_boolean_logprobs() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "input": "lp int", "logprobs": 5},
        )
        assert status == 400, body
        assert "invalid_logprobs" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_accepts_empty_and_valid_logit_bias()
    test_http_responses_rejects_non_digit_logit_bias_key()
    test_http_responses_rejects_out_of_range_logit_bias_value()
    test_http_responses_accepts_logprobs_false()
    test_http_responses_accepts_logprobs_true_with_top_logprobs()
    test_http_responses_rejects_top_logprobs_without_logprobs()
    test_http_responses_rejects_non_boolean_logprobs()
    print("ok")
