"""logit_bias digit-key whitespace strip over HTTP."""

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

_TEST_AUTH_TOKEN = "logit_bias_key_strip_http_honesty_token"  # noqa: S105


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


def test_http_responses_rejects_unapplied_logit_bias_padded_digit_keys() -> None:
    server, thread, port = _server()
    try:
        for key in ("100", " 100 ", "\t42\t", "  7"):
            status, body = _post(
                port,
                "/v1/responses",
                {
                    "model": "mock-planner",
                    "input": f"bias key {key!r}",
                    "logit_bias": {key: "-5", "200": 1},
                },
            )
            assert status == 400, (key, body)
            assert "unsupported_responses_orchestration_controls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_still_rejects_non_digit_logit_bias_keys() -> None:
    server, thread, port = _server()
    try:
        for key in ("abc", "12a", " ", "", "1.5", "-1"):
            status, body = _post(
                port,
                "/v1/responses",
                {
                    "model": "mock-planner",
                    "input": f"bias bad key {key!r}",
                    "logit_bias": {key: 1},
                },
            )
            assert status == 400, (key, body)
            assert "invalid_logit_bias" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_typechecks_padded_keys_then_rejects_nonempty() -> None:
    """Chat has no bias plane; padded digit keys type-check then fail closed."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bias chat"}],
                "logit_bias": {" 100 ": "-5"},
            },
        )
        assert status == 400, body
        dumped = json.dumps(body)
        assert "invalid_logit_bias" in dumped
        assert "not supported" in dumped
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_still_typechecks_padded_keys_then_rejects_nonempty() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "bias completions",
                "logit_bias": {"\t9\t": 0},
            },
        )
        assert status == 400, body
        dumped = json.dumps(body)
        assert "invalid_logit_bias" in dumped
        assert "not supported" in dumped
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_rejects_unapplied_logit_bias_padded_digit_keys()
    test_http_responses_still_rejects_non_digit_logit_bias_keys()
    test_http_chat_still_typechecks_padded_keys_then_rejects_nonempty()
    test_http_completions_still_typechecks_padded_keys_then_rejects_nonempty()
    print("ok")
