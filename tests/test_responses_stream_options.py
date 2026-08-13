"""OpenAI Responses stream_options validation."""

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
    _validate_responses_stream_options,
    build_server,
)

_TEST_AUTH_TOKEN = "resp_so_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_stream_options() -> None:
    assert _validate_responses_stream_options({}) is None
    assert _validate_responses_stream_options(
        {"stream_options": {"include_usage": True}}
    ) == {"include_usage": True}
    try:
        _validate_responses_stream_options({"stream_options": {"foo": 1}})
        raise AssertionError("unknown key")
    except RequestError as exc:
        assert exc.code == "invalid_stream_options"
    try:
        _validate_responses_stream_options({"stream_options": {"include_usage": 1}})
        raise AssertionError("non-bool")
    except RequestError as exc:
        assert exc.code == "invalid_stream_options"


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/responses",
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


def test_http_accepts_stream_options() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "hi",
                "stream": False,
                "stream_options": {"include_usage": True},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_rejects_unknown_stream_options_key() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "hi",
                "stream_options": {"include_usage": True, "extra": False},
            },
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_stream_options"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_stream_options()
    test_http_accepts_stream_options()
    test_http_rejects_unknown_stream_options_key()
    print("ok")
