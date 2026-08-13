"""Completions best_of/echo/suffix/logprobs honesty: HTTP fail-closed contracts."""

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

_TEST_AUTH_TOKEN = "completions_legacy_knobs_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


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


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_completions_baseline_ok() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "draft a one-line payment receipt"},
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_best_of_one_ok() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hi", "best_of": 1},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_best_of_multi_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hi", "best_of": 3},
        )
        assert status == 400, body
        assert "invalid_best_of" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_echo_false_ok() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hi", "echo": False},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_echo_true_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hi", "echo": True},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_echo" in blob
        assert "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_empty_suffix_ok() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hi", "suffix": ""},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_nonempty_suffix_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "function head(",
                "suffix": ") { return 1; }",
            },
        )
        assert status == 400, body
        assert "invalid_suffix" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_logprobs_false_ok() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hi", "logprobs": False},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_logprobs_integer_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hi", "logprobs": 5},
        )
        assert status == 400, body
        assert "invalid_logprobs" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_logprobs_true_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hi", "logprobs": True},
        )
        assert status == 400, body
        assert "invalid_logprobs" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_baseline_ok()
    test_http_completions_best_of_one_ok()
    test_http_completions_best_of_multi_fail_closed()
    test_http_completions_echo_false_ok()
    test_http_completions_echo_true_fail_closed()
    test_http_completions_empty_suffix_ok()
    test_http_completions_nonempty_suffix_fail_closed()
    test_http_completions_logprobs_false_ok()
    test_http_completions_logprobs_integer_fail_closed()
    test_http_completions_logprobs_true_fail_closed()
    print("ok")
