"""logit_bias numeric-string value coerce over HTTP."""

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

_TEST_AUTH_TOKEN = "logit_bias_numeric_string_coerce_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


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


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_responses_accepts_logit_bias_numeric_string_values() -> None:
    server, thread, port = _server()
    try:
        for val in ("-5", "0", "100", " -12.5 ", 0, -5.0, 100):
            status, body = _post(
                port,
                "/v1/responses",
                {
                    "model": "mock-planner",
                    "input": f"bias {val!r}",
                    "logit_bias": {"100": val, "200": 1},
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_still_rejects_logit_bias_bool_and_oob() -> None:
    server, thread, port = _server()
    try:
        for bias in ({"1": True}, {"1": 101}, {"1": "-101"}, {"abc": 1}):
            status, body = _post(
                port,
                "/v1/responses",
                {
                    "model": "mock-planner",
                    "input": f"bias bad {bias!r}",
                    "logit_bias": bias,
                },
            )
            assert status == 400, (bias, body)
            assert "invalid_logit_bias" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_nonempty_logit_bias_after_type_check() -> None:
    """Chat/Completions have no bias plane; non-empty maps fail closed after coerce."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bias chat"}],
                "logit_bias": {"100": "-5"},
            },
        )
        assert status == 400, body
        assert "invalid_logit_bias" in json.dumps(body)
        assert "not supported" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_accepts_logit_bias_numeric_string_values()
    test_http_responses_still_rejects_logit_bias_bool_and_oob()
    test_http_chat_still_rejects_nonempty_logit_bias_after_type_check()
    print("ok")
