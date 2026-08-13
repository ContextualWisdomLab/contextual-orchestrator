"""OpenAI stream_options shape validation and include_usage SSE framing."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import chat_completion_chunks  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _validate_stream_options,
    build_server,
)

_TEST_AUTH_TOKEN = "stream_opts_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_stream_options() -> None:
    assert _validate_stream_options(None) is None
    assert _validate_stream_options({"include_usage": True}) == {"include_usage": True}
    assert _validate_stream_options({}) == {"include_usage": False}
    try:
        _validate_stream_options("nope")
        raise AssertionError("expected non-object")
    except RequestError as exc:
        assert exc.code == "invalid_stream_options"
    try:
        _validate_stream_options({"include_usage": True, "extra": 1})
        raise AssertionError("expected unknown key")
    except RequestError as exc:
        assert exc.code == "invalid_stream_options"
    try:
        _validate_stream_options({"include_usage": "yes"})
        raise AssertionError("expected bool")
    except RequestError as exc:
        assert exc.code == "invalid_stream_options"


def test_chat_completion_chunks_include_usage() -> None:
    result = {"answer": "hi", "mode": "route", "workflow_run_id": "run_x"}
    chunks = chat_completion_chunks(result, include_usage=True, usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
    assert chunks[-1]["choices"] == []
    assert chunks[-1]["usage"]["total_tokens"] == 3
    assert chunks[-2]["choices"][0]["finish_reason"] == "stop"


def test_http_stream_options_accepted() -> None:
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
                    "stream": True,
                    "stream_options": {"include_usage": True},
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
            body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert "data: [DONE]" in body
    assert '"usage"' in body
    assert '"choices": []' in body or '"choices":[]' in body


def test_http_stream_options_invalid_rejected() -> None:
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
                    "stream_options": {"include_usage": "yes"},
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
            assert body["error"]["code"] == "invalid_stream_options"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_stream_options()
    test_chat_completion_chunks_include_usage()
    test_http_stream_options_accepted()
    test_http_stream_options_invalid_rejected()
    print("ok")
