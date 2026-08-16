"""include_orchestration_trace string/0-1 bool coerce over HTTP."""

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

_TEST_AUTH_TOKEN = "include_orchestration_trace_bool_coerce_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
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
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, expose_trace_by_default=False),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_include_orchestration_trace_string_true_false() -> None:
    server, thread, port = _server()
    try:
        for val in ("true", "false", "TRUE", " False ", "1", "0"):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"iot str {val!r}"}],
                    "include_orchestration_trace": val,
                },
            )
            assert status == 200, (val, body)
            assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_include_orchestration_trace_int_0_1() -> None:
    server, thread, port = _server()
    try:
        for val in (0, 1):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"iot int {val}"}],
                    "include_orchestration_trace": val,
                },
            )
            assert status == 200, (val, body)
            assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_include_orchestration_trace_yes() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "iot yes"}],
                "include_orchestration_trace": "yes",
            },
        )
        assert status == 400, body
        assert "invalid_include_orchestration_trace" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_attribution_null_empty_value_omit() -> None:
    """Null/empty known-dimension values omit rather than stringify to 'None'."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "attr omit vals"}],
                "attribution": {"team": None, "company": "", "account": "  ", "service": "api"},
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_attribution_all_null_values_as_empty_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "attr all null"}],
                "attribution": {"team": None, "company": ""},
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_include_orchestration_trace_string_true_false()
    test_http_chat_accepts_include_orchestration_trace_int_0_1()
    test_http_chat_still_rejects_include_orchestration_trace_yes()
    test_http_chat_accepts_attribution_null_empty_value_omit()
    test_http_chat_accepts_attribution_all_null_values_as_empty_object()
    print("ok")
