"""Strict boolean validation for include_orchestration_trace on chat."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _validate_include_orchestration_trace,
    build_server,
)

_TEST_AUTH_TOKEN = "include_trace_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_include_orchestration_trace() -> None:
    assert _validate_include_orchestration_trace({}, default=False) is False
    assert _validate_include_orchestration_trace({}, default=True) is True
    assert _validate_include_orchestration_trace(
        {"include_orchestration_trace": True}, default=False
    ) is True
    assert _validate_include_orchestration_trace(
        {"include_orchestration_trace": False}, default=True
    ) is False
    try:
        _validate_include_orchestration_trace(
            {"include_orchestration_trace": "false"}, default=False
        )
        raise AssertionError("string truthy trap")
    except RequestError as exc:
        assert exc.code == "invalid_include_orchestration_trace"
    try:
        _validate_include_orchestration_trace(
            {"include_orchestration_trace": 1}, default=False
        )
        raise AssertionError("int")
    except RequestError as exc:
        assert exc.code == "invalid_include_orchestration_trace"


def test_http_include_trace_accepted() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "orchestration": "route",
                    "include_orchestration_trace": True,
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert body["object"] == "chat.completion"
    assert "orchestration" in body
    assert "trace" in body["orchestration"] or body["orchestration"].get("mode")


def test_http_include_trace_string_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "include_orchestration_trace": "false",
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert body["error"]["code"] == "invalid_include_orchestration_trace"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_include_orchestration_trace()
    test_http_include_trace_accepted()
    test_http_include_trace_string_rejected()
    print("ok")
