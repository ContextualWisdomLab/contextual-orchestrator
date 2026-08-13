"""Legacy Completions stream_options: object with bool flags; requires stream=true."""

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
    _validate_completions_stream_options,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_stream_opts_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_completions_stream_options() -> None:
    assert _validate_completions_stream_options({}) is None
    assert _validate_completions_stream_options(
        {"stream": True, "stream_options": {"include_usage": True}}
    ) == {"include_usage": True}
    assert _validate_completions_stream_options(
        {
            "stream": True,
            "stream_options": {"include_usage": False, "include_obfuscation": True},
        }
    ) == {"include_usage": False, "include_obfuscation": True}

    try:
        _validate_completions_stream_options({"stream_options": {"include_usage": True}})
        raise AssertionError("expected requires stream=true")
    except RequestError as exc:
        assert exc.code == "invalid_stream_options"

    try:
        _validate_completions_stream_options(
            {"stream": False, "stream_options": {"include_usage": True}}
        )
        raise AssertionError("expected requires stream=true with false")
    except RequestError as exc:
        assert exc.code == "invalid_stream_options"

    try:
        _validate_completions_stream_options({"stream": True, "stream_options": "bad"})
        raise AssertionError("expected object")
    except RequestError as exc:
        assert exc.code == "invalid_stream_options"

    try:
        _validate_completions_stream_options(
            {"stream": True, "stream_options": {"include_usage": "yes"}}
        )
        raise AssertionError("expected include_usage bool")
    except RequestError as exc:
        assert exc.code == "invalid_stream_options"

    try:
        _validate_completions_stream_options(
            {"stream": True, "stream_options": {"include_obfuscation": 1}}
        )
        raise AssertionError("expected include_obfuscation bool")
    except RequestError as exc:
        assert exc.code == "invalid_stream_options"

    try:
        _validate_completions_stream_options(
            {"stream": True, "stream_options": {"unknown_flag": True}}
        )
        raise AssertionError("expected unknown field")
    except RequestError as exc:
        assert exc.code == "invalid_stream_options"
        assert "unknown_flag" in exc.detail.get("fields", [])


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


def test_http_rejects_stream_options_without_stream_true() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello",
                "stream_options": {"include_usage": True},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_stream_options"
        assert "stream=true" in body["error"]["message"]

        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello",
                "stream": False,
                "stream_options": {"include_usage": True},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_stream_options"

        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello",
                "stream": False,
                "stream_options": "not-an-object",
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_stream_options"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_stream_true_with_options_redirects() -> None:
    """stream=true is rejected before stream_options can succeed (no Completions SSE)."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello",
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_stream"
        assert "chat/completions" in body["error"]["message"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_without_stream_options() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "prompt": "hello world", "stream": False},
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert body["choices"][0]["text"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_completions_stream_options()
    test_http_rejects_stream_options_without_stream_true()
    test_http_stream_true_with_options_redirects()
    test_http_accepts_without_stream_options()
