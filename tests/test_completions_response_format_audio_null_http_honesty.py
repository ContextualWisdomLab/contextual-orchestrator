"""Completions empty response_format/prediction and audio null omit honesty."""

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

_TEST_AUTH_TOKEN = "completions_response_format_audio_null_http_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
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


def test_http_completions_accepts_empty_response_format_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "rf empty", "response_format": ""},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_empty_prediction_and_reasoning_effort_strings() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "pred effort empty",
                "prediction": "",
                "reasoning_effort": "  ",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_audio_and_web_search_null() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "audio null",
                "audio": None,
                "web_search_options": None,
            },
        )
        assert status == 200, body
        assert "unknown_fields" not in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_empty_audio_object() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "audio empty", "audio": {}},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_nonempty_audio() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "audio voice",
                "audio": {"voice": "alloy", "format": "mp3"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_audio" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_accepts_empty_response_format_string()
    test_http_completions_accepts_empty_prediction_and_reasoning_effort_strings()
    test_http_completions_accepts_audio_and_web_search_null()
    test_http_completions_accepts_empty_audio_object()
    test_http_completions_rejects_nonempty_audio()
    print("ok")
