"""Strict stream boolean validation on chat and Responses API."""

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
    _validate_stream_flag,
    build_server,
)

_TEST_AUTH_TOKEN = "stream_bool_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_stream_flag() -> None:
    assert _validate_stream_flag({}) is False
    assert _validate_stream_flag({"stream": True}) is True
    assert _validate_stream_flag({"stream": False}) is False
    try:
        _validate_stream_flag({"stream": "true"})
        raise AssertionError("string")
    except RequestError as exc:
        assert exc.code == "invalid_stream"
    try:
        _validate_stream_flag({"stream": 1})
        raise AssertionError("int")
    except RequestError as exc:
        assert exc.code == "invalid_stream"


def test_http_responses_stream_false_accepted() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/responses",
            data=json.dumps(
                {
                    "model": "mock-generalist",
                    "input": "hello",
                    "stream": False,
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
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_stream_string_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/responses",
            data=json.dumps(
                {
                    "input": "hello",
                    "stream": "yes",
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
            assert body["error"]["code"] == "invalid_stream"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_stream_flag()
    test_http_responses_stream_false_accepted()
    test_http_responses_stream_string_rejected()
    print("ok")
