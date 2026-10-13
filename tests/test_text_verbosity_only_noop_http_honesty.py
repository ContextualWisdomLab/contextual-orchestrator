"""Responses text.verbosity without a format plane is a default-length no-op."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "text_verbosity_only_noop_http_honesty_token"  # noqa: S105


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
        with exc:
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


def test_http_responses_accepts_text_verbosity_without_format() -> None:
    """SDKs send text.verbosity alone; known levels stay default-length no-ops."""
    server, thread, port = _server()
    try:
        for val in ("low", "MEDIUM", " High ", "high"):
            status, body = _post(
                port,
                "/v1/responses",
                {
                    "model": "mock-planner",
                    "input": f"text v only {val!r}",
                    "text": {"verbosity": val},
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_http_responses_accepts_text_verbosity_with_null_format() -> None:
    """Null, empty, or blank format plus a known verbosity is still a no-op."""
    server, thread, port = _server()
    try:
        for fmt in (None, {}, ""):
            status, body = _post(
                port,
                "/v1/responses",
                {
                    "model": "mock-planner",
                    "input": f"text v null-format {fmt!r}",
                    "text": {"format": fmt, "verbosity": "low"},
                },
            )
            assert status == 200, (fmt, body)
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "text v blank-type",
                "text": {"format": {"type": None}, "verbosity": "medium"},
            },
        )
        assert status == 200, body
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "text v blank-type-str",
                "text": {"format": {"type": "  "}, "verbosity": "high"},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_http_responses_rejects_verbosity_only_with_response_format() -> None:
    """Verbosity-only acceptance must not open a second response_format plane."""
    server, thread, port = _server()
    try:
        payloads = (
            {"verbosity": "low"},
            {"format": None, "verbosity": "medium"},
            {"format": {"type": "  "}, "verbosity": "high"},
        )
        for text in payloads:
            status, body = _post(
                port,
                "/v1/responses",
                {
                    "model": "mock-planner",
                    "input": "text v dual plane",
                    "text": text,
                    "response_format": {"type": "text"},
                },
            )
            assert status == 400, (text, body)
            assert "invalid_text" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_http_responses_still_rejects_unknown_text_verbosity_only() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "text v max only",
                "text": {"verbosity": "max"},
            },
        )
        assert status == 400, body
        assert "invalid_text" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


if __name__ == "__main__":
    test_http_responses_accepts_text_verbosity_without_format()
    test_http_responses_accepts_text_verbosity_with_null_format()
    test_http_responses_rejects_verbosity_only_with_response_format()
    test_http_responses_still_rejects_unknown_text_verbosity_only()
    print("ok")
