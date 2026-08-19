"""Whole-float 0.0/1.0 and "0.0"/"1.0" optional-bool coerce honesty over HTTP."""

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

_TEST_AUTH_TOKEN = "bool_whole_float_zero_one_coerce_http_honesty_token"  # noqa: S105

_FALSEY_WHOLE = (0.0, "0.0", " 0.0 ", "0.00")
_TRUTHY_WHOLE = (1.0, "1.0", " 1.0 ", "1.00")


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent(
                "general_agent",
                "mock-planner",
                tags=("reasoning", "writing", "embedding"),
            )
        ]
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


def test_http_chat_accepts_store_whole_float_false() -> None:
    server, thread, port = _server()
    try:
        for value in _FALSEY_WHOLE:
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"store {value!r}"}],
                    "store": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_store_whole_float_true() -> None:
    """store=true (including 1.0) remains unsupported — fail closed."""
    server, thread, port = _server()
    try:
        for value in _TRUTHY_WHOLE:
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"store t {value!r}"}],
                    "store": value,
                },
            )
            assert status == 400, (value, body)
            assert "invalid_store" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_stream_whole_float_false() -> None:
    server, thread, port = _server()
    try:
        for value in _FALSEY_WHOLE:
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"stream {value!r}"}],
                    "stream": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_parallel_tool_calls_whole_float_false() -> None:
    server, thread, port = _server()
    try:
        for value in _FALSEY_WHOLE:
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"ptc {value!r}"}],
                    "parallel_tool_calls": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_logprobs_whole_float_false() -> None:
    server, thread, port = _server()
    try:
        for value in _FALSEY_WHOLE:
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"lp {value!r}"}],
                    "logprobs": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_logprobs_whole_float_true() -> None:
    server, thread, port = _server()
    try:
        for value in _TRUTHY_WHOLE:
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"lp t {value!r}"}],
                    "logprobs": value,
                },
            )
            assert status == 400, (value, body)
            assert "invalid_logprobs" in json.dumps(body) or "logprobs" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_whole_float_bools() -> None:
    server, thread, port = _server()
    try:
        for field, value in (
            ("store", 0.5),
            ("store", "0.5"),
            ("stream", 1.5),
            ("stream", "2.0"),
            ("parallel_tool_calls", -1.0),
            ("logprobs", "truee"),
        ):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"bad {field} {value!r}"}],
                    field: value,
                },
            )
            assert status == 400, (field, value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_echo_stream_whole_float_false() -> None:
    server, thread, port = _server()
    try:
        for field in ("echo", "stream"):
            for value in _FALSEY_WHOLE:
                status, body = _post(
                    port,
                    "/v1/completions",
                    {
                        "model": "mock-planner",
                        "prompt": f"{field} {value!r}",
                        field: value,
                    },
                )
                assert status == 200, (field, value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_include_orchestration_trace_whole_float_false() -> None:
    server, thread, port = _server()
    try:
        for value in _FALSEY_WHOLE:
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"iot {value!r}"}],
                    "include_orchestration_trace": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_routing_latency_tolerant_whole_float_false() -> None:
    server, thread, port = _server()
    try:
        for value in _FALSEY_WHOLE:
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"rt {value!r}"}],
                    "routing": {"latency_tolerant": value},
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_background_store_whole_float_false() -> None:
    server, thread, port = _server()
    try:
        for field in ("background", "store"):
            for value in _FALSEY_WHOLE:
                status, body = _post(
                    port,
                    "/v1/responses",
                    {
                        "model": "mock-planner",
                        "input": f"{field} {value!r}",
                        field: value,
                    },
                )
                assert status == 200, (field, value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)
