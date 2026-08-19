"""Whole-float string int coerce + top_logprobs/max_tool_calls zero omit over HTTP."""

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

_TEST_AUTH_TOKEN = "whole_float_string_int_coerce_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=15) as response:
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


def test_http_chat_accepts_n_whole_float_string() -> None:
    server, thread, port = _server()
    try:
        for val in ("1.0", " 1.00 ", "1"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"n {val!r}"}],
                    "n": val,
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_seed_whole_float_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "seed float str",
                "seed": "1.0",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_fractional_float_string_n() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "n frac"}],
                "n": "1.5",
            },
        )
        assert status == 400, body
        assert "invalid_n" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_top_logprobs_zero_float_strings() -> None:
    server, thread, port = _server()
    try:
        for val in (0, "0", 0.0, "0.0", " 0.0 ", "00"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"tlp {val!r}"}],
                    "top_logprobs": val,
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_nonzero_top_logprobs_float_string() -> None:
    server, thread, port = _server()
    try:
        for val in (1, "3", 2.0, "5.0"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"tlp bad {val!r}"}],
                    "top_logprobs": val,
                },
            )
            assert status == 400, (val, body)
            assert "invalid_top_logprobs" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_top_logprobs_zero_float_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "tlp zero float str",
                "top_logprobs": "0.0",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_best_of_whole_float_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "best_of float str",
                "best_of": "1.0",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_max_tool_calls_zero_float_string() -> None:
    server, thread, port = _server()
    try:
        for val in ("0.0", " 0.00 "):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"mtc {val!r}"}],
                    "max_tool_calls": val,
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_top_logprobs_whole_float_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "tlp float str responses",
                "logprobs": True,
                "top_logprobs": "5.0",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_n_whole_float_string()
    test_http_responses_accepts_seed_whole_float_string()
    test_http_chat_rejects_fractional_float_string_n()
    test_http_chat_accepts_top_logprobs_zero_float_strings()
    test_http_chat_still_rejects_nonzero_top_logprobs_float_string()
    test_http_completions_accepts_top_logprobs_zero_float_string()
    test_http_completions_accepts_best_of_whole_float_string()
    test_http_chat_accepts_max_tool_calls_zero_float_string()
    test_http_responses_accepts_top_logprobs_whole_float_string()
    print("ok")
