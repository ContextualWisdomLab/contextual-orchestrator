"""stream_options null flag values are omit-equivalent no-ops over HTTP."""

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

_TEST_AUTH_TOKEN = "stream_options_null_flags_noop_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post_raw(port: int, path: str, payload: dict) -> tuple[int, str, str]:
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
            return (
                response.status,
                response.headers.get("content-type", ""),
                response.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", ""), exc.read().decode("utf-8")


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_stream_options_null_flags_without_stream() -> None:
    """SDK optional null flags must not require stream=true or fail type checks."""
    server, thread, port = _server()
    try:
        for opts in (
            {"include_usage": None},
            {"include_obfuscation": None},
            {"include_usage": None, "include_obfuscation": None},
            {"include_usage": None, "include_obfuscation": False},
            {"include_usage": False, "include_obfuscation": None},
        ):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "null so flags"}],
                    "stream": False,
                    "stream_options": opts,
                },
            )
            assert status == 200, (opts, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_stream_options_null_flags_without_stream() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "null so flags",
                "stream": False,
                "stream_options": {
                    "include_usage": None,
                    "include_obfuscation": None,
                },
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_stream_options_null_flags() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "null so flags",
                "stream_options": {
                    "include_usage": None,
                    "include_obfuscation": None,
                },
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_include_usage_true() -> None:
    server, thread, port = _server()
    try:
        status, content_type, sse = _post_raw(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "usage true"}],
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        )
        assert status == 200, sse
        assert content_type.startswith("text/event-stream")
        frames = [
            json.loads(frame[len("data: "):])
            for frame in sse.split("\n\n")
            if frame.startswith("data: ") and frame != "data: [DONE]"
        ]
        usage = next(frame for frame in frames if frame.get("choices") == [])
        assert usage["usage"]["usage_source"] == "estimated"
        assert usage["usage"]["completion_tokens"] > 0
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_structured_streams_include_usage() -> None:
    server, thread, port = _server()
    try:
        for structured in (
            {
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ]
            },
            {"response_format": {"type": "json_object"}},
        ):
            status, content_type, sse = _post_raw(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "structured usage"}],
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    **structured,
                },
            )
            assert status == 200, (structured, sse)
            assert content_type.startswith("text/event-stream")
            frames = [
                json.loads(frame[len("data: "):])
                for frame in sse.split("\n\n")
                if frame.startswith("data: ") and frame != "data: [DONE]"
            ]
            usage = next(frame for frame in frames if frame.get("choices") == [])
            assert usage["usage"]["usage_source"] in {"reported", "estimated"}
            assert usage["usage"]["total_tokens"] >= 0
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_boolean_non_null_flag() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bad flag"}],
                "stream": True,
                "stream_options": {"include_usage": "yes"},
            },
        )
        assert status == 400, body
        assert "invalid_stream_options" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_stream_options_null_flags_without_stream()
    test_http_completions_accepts_stream_options_null_flags_without_stream()
    test_http_responses_accepts_stream_options_null_flags()
    test_http_chat_accepts_include_usage_true()
    test_http_chat_structured_streams_include_usage()
    test_http_chat_rejects_non_boolean_non_null_flag()
    print("ok")
