"""routing.latency_tolerant + stream_options string/0-1 bool coerce over HTTP."""

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

_TEST_AUTH_TOKEN = "routing_latency_stream_options_bool_coerce_http_honesty_token"  # noqa: S105


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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_routing_latency_tolerant_string_true() -> None:
    """latency_tolerant 'true'/1 selects batch channel (202 job handle)."""
    server, thread, port = _server()
    try:
        for val in ("true", "TRUE", 1, "1"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"batch {val!r}"}],
                    "routing": {"latency_tolerant": val},
                },
            )
            assert status == 202, (val, body)
            assert body.get("channel") == "batch" or "job_id" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_routing_latency_tolerant_string_false() -> None:
    server, thread, port = _server()
    try:
        for val in ("false", 0, "0"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"sync {val!r}"}],
                    "routing": {"latency_tolerant": val},
                },
            )
            assert status == 200, (val, body)
            assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_routing_latency_tolerant_yes() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "latency yes"}],
                "routing": {"latency_tolerant": "yes"},
            },
        )
        assert status == 400, body
        assert "invalid_routing" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_stream_options_include_usage_false_string() -> None:
    """include_usage 'false'/0 is omit-equivalent even without stream=true."""
    server, thread, port = _server()
    try:
        for val in ("false", 0, "0", False):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"so {val!r}"}],
                    "stream": False,
                    "stream_options": {"include_usage": val},
                },
            )
            assert status == 200, (val, body)
            assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_stream_options_include_usage_true_string_without_stream() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "so true needs stream"}],
                "stream": False,
                "stream_options": {"include_usage": "true"},
            },
        )
        assert status == 400, body
        assert "invalid_stream_options" in json.dumps(body)
        assert "stream" in json.dumps(body).lower()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_response_format_empty_type_as_omit() -> None:
    server, thread, port = _server()
    try:
        for fmt in ({"type": ""}, {"type": "  "}, {"type": None}):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"rf {fmt!r}"}],
                    "response_format": fmt,
                },
            )
            assert status == 200, (fmt, body)
            assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_top_logprobs_digit_string_with_logprobs() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "tlp digit",
                "logprobs": True,
                "top_logprobs": "5",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_routing_latency_tolerant_string_true()
    test_http_chat_accepts_routing_latency_tolerant_string_false()
    test_http_chat_still_rejects_routing_latency_tolerant_yes()
    test_http_chat_accepts_stream_options_include_usage_false_string()
    test_http_chat_still_rejects_stream_options_include_usage_true_string_without_stream()
    test_http_chat_accepts_response_format_empty_type_as_omit()
    test_http_responses_accepts_top_logprobs_digit_string_with_logprobs()
    print("ok")
