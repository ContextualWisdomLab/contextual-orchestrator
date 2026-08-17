"""Responses reasoning.none omit, text.format empty type, logprobs 0.0, dimensions 0."""

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

_TEST_AUTH_TOKEN = "reasoning_none_text_empty_logprobs_zero_http_honesty_token"  # noqa: S105


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


def test_http_responses_accepts_reasoning_effort_none_omit() -> None:
    server, thread, port = _server()
    try:
        for val in (
            {"effort": "none"},
            {"effort": "NONE"},
            {"effort": " none "},
            {"effort": None},
            {"effort": ""},
            {"effort": "none", "summary": None},
            {"effort": "none", "summary": ""},
        ):
            status, body = _post(
                port,
                "/v1/responses",
                {"model": "mock-planner", "input": f"reason {val!r}", "reasoning": val},
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_still_rejects_reasoning_effort_low() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "reason low",
                "reasoning": {"effort": "low"},
            },
        )
        assert status == 400, body
        assert "invalid_reasoning" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_text_format_empty_type_omit() -> None:
    server, thread, port = _server()
    try:
        for fmt in ({"type": ""}, {"type": "  "}, {"type": None}):
            status, body = _post(
                port,
                "/v1/responses",
                {
                    "model": "mock-planner",
                    "input": f"text {fmt!r}",
                    "text": {"format": fmt},
                },
            )
            assert status == 200, (fmt, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_logprobs_zero_float_string_omit() -> None:
    server, thread, port = _server()
    try:
        for val in ("0.0", "0.00", " 0.0 ", 0.0, "0"):
            status, body = _post(
                port,
                "/v1/completions",
                {
                    "model": "mock-planner",
                    "prompt": f"lp {val!r}",
                    "logprobs": val,
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_accepts_dimensions_zero_omit() -> None:
    server, thread, port = _server()
    try:
        for val in (0, "0", "0.0", 0.0):
            status, body = _post(
                port,
                "/v1/embeddings",
                {
                    "model": "mock-planner",
                    "input": f"dim {val!r}",
                    "dimensions": val,
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_embeddings_still_rejects_dimensions_nonzero() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/embeddings",
            {"model": "mock-planner", "input": "dim 8", "dimensions": 8},
        )
        assert status == 400, body
        assert "invalid_dimensions" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_accepts_reasoning_effort_none_omit()
    test_http_responses_still_rejects_reasoning_effort_low()
    test_http_responses_accepts_text_format_empty_type_omit()
    test_http_completions_accepts_logprobs_zero_float_string_omit()
    test_http_embeddings_accepts_dimensions_zero_omit()
    test_http_embeddings_still_rejects_dimensions_nonzero()
    print("ok")
