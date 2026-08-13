"""OpenAI logprobs / top_logprobs type validation on chat completions."""

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
    _validate_logprobs_fields,
    build_server,
)

_TEST_AUTH_TOKEN = "logprobs_type_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_logprobs_fields() -> None:
    assert _validate_logprobs_fields({}) == {}
    assert _validate_logprobs_fields({"logprobs": True}) == {"logprobs": True}
    assert _validate_logprobs_fields({"logprobs": True, "top_logprobs": 5}) == {
        "logprobs": True,
        "top_logprobs": 5,
    }
    try:
        _validate_logprobs_fields({"logprobs": 1})
        raise AssertionError("non-bool")
    except RequestError as exc:
        assert exc.code == "invalid_logprobs"
    try:
        _validate_logprobs_fields({"logprobs": True, "top_logprobs": 21})
        raise AssertionError("range")
    except RequestError as exc:
        assert exc.code == "invalid_top_logprobs"
    try:
        _validate_logprobs_fields({"top_logprobs": 3})
        raise AssertionError("requires logprobs true")
    except RequestError as exc:
        assert exc.code == "invalid_top_logprobs"
    try:
        _validate_logprobs_fields({"logprobs": True, "top_logprobs": 1.5})
        raise AssertionError("float")
    except RequestError as exc:
        assert exc.code == "invalid_top_logprobs"


def test_http_logprobs_accepted() -> None:
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
                    "logprobs": False,
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


def test_http_top_logprobs_without_logprobs_rejected() -> None:
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
                    "top_logprobs": 5,
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
            assert body["error"]["code"] == "invalid_top_logprobs"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_logprobs_fields()
    test_http_logprobs_accepted()
    test_http_top_logprobs_without_logprobs_rejected()
    print("ok")
