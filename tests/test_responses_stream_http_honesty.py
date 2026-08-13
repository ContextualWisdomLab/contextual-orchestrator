"""Responses stream honesty: omit/false ok; true and non-bool fail-closed."""

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

_TEST_AUTH_TOKEN = "responses_stream_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


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


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_responses_omits_stream_ok() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-generalist", "input": "summarize the invoice note"},
        )
        assert status == 200, body
        assert body.get("object") == "response" or "output" in body or "id" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_stream_false_ok() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "summarize the invoice note",
                "stream": False,
            },
        )
        assert status == 200, body
        assert isinstance(body, dict)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_stream_true_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "summarize the invoice note",
                "stream": True,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_stream" in blob
        assert "not supported" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_stream_non_boolean_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "input": "x",
                "stream": "false",
            },
        )
        assert status == 400, body
        assert "invalid_stream" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_stream_options_include_obfuscation_true_fail_closed() -> None:
    """Chat stream_options.include_obfuscation=true is not applied; fail closed."""
    server, thread, port = _server()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "mock-generalist",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                    "stream_options": {"include_obfuscation": True},
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
            with urllib.request.urlopen(request, timeout=10) as response:
                status = response.status
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        assert status == 400, body
        assert "invalid_stream_options" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_omits_stream_ok()
    test_http_responses_stream_false_ok()
    test_http_responses_stream_true_fail_closed()
    test_http_responses_stream_non_boolean_fail_closed()
    test_http_chat_stream_options_include_obfuscation_true_fail_closed()
    print("ok")
