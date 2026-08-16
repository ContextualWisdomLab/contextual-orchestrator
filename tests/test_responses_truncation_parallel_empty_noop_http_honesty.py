"""Responses truncation auto|disabled and empty-string parallel_tool_calls no-ops over HTTP."""

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

_TEST_AUTH_TOKEN = "responses_truncation_parallel_empty_noop_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(path: str, port: int, payload: dict) -> tuple[int, dict]:
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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_responses_truncation_auto_disabled_noop() -> None:
    server, thread, port = _server()
    try:
        for truncation in ("auto", "disabled", None, "", "  "):
            payload: dict = {"model": "mock-planner", "input": "truncation noop"}
            if truncation is not None or truncation == "":
                # Always include key for "" / whitespace; skip only when intentionally omitted.
                pass
            if truncation is not None:
                payload["truncation"] = truncation
            # For None we still send the key as JSON null.
            if truncation is None:
                payload["truncation"] = None
            status, body = _post("/v1/responses", port, payload)
            assert status == 200, (truncation, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_non_enum_truncation() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            "/v1/responses",
            port,
            {
                "model": "mock-planner",
                "input": "bad truncation",
                "truncation": "aggressive",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_truncation" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_still_rejects_previous_response_id() -> None:
    """State-changing conversation controls remain fail-closed with named errors."""
    server, thread, port = _server()
    try:
        status, body = _post(
            "/v1/responses",
            port,
            {
                "model": "mock-planner",
                "input": "prev",
                "previous_response_id": "resp_x",
                "truncation": "auto",
            },
        )
        assert status == 400, body
        assert "invalid_previous_response_id" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_parallel_tool_calls_empty_string_noop() -> None:
    server, thread, port = _server()
    try:
        for value in ("", "  ", None):
            status, body = _post(
                "/v1/chat/completions",
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "ptc empty"}],
                    "parallel_tool_calls": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_parallel_tool_calls_empty_string_noop() -> None:
    server, thread, port = _server()
    try:
        for value in ("", "  ", None, False):
            status, body = _post(
                "/v1/responses",
                port,
                {
                    "model": "mock-planner",
                    "input": "ptc empty",
                    "parallel_tool_calls": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_parallel_tool_calls_true_without_tools_still_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            "/v1/chat/completions",
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "ptc true"}],
                "parallel_tool_calls": True,
            },
        )
        assert status == 400, body
        assert "invalid_parallel_tool_calls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_parallel_tool_calls_empty_string_noop() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            "/v1/completions",
            port,
            {
                "model": "mock-planner",
                "prompt": "ptc empty completions",
                "parallel_tool_calls": "",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_truncation_auto_disabled_noop()
    test_http_responses_rejects_non_enum_truncation()
    test_http_responses_still_rejects_previous_response_id()
    test_http_chat_parallel_tool_calls_empty_string_noop()
    test_http_responses_parallel_tool_calls_empty_string_noop()
    test_http_chat_parallel_tool_calls_true_without_tools_still_fail_closed()
    test_http_completions_parallel_tool_calls_empty_string_noop()
    print("ok")
