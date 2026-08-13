"""OpenAI top_p and presence/frequency_penalty validation on chat completions."""

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
    _validate_penalty_fields,
    _validate_top_p,
    build_server,
)

_TEST_AUTH_TOKEN = "top_p_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_top_p_and_penalties() -> None:
    assert _validate_top_p({}) is None
    assert _validate_top_p({"top_p": 0.9}) == 0.9
    try:
        _validate_top_p({"top_p": 1.5})
        raise AssertionError("expected invalid_top_p")
    except RequestError as exc:
        assert exc.code == "invalid_top_p"
    assert _validate_penalty_fields({"presence_penalty": 0.5, "frequency_penalty": -1}) == {
        "presence_penalty": 0.5,
        "frequency_penalty": -1.0,
    }
    try:
        _validate_penalty_fields({"presence_penalty": 3})
        raise AssertionError("expected invalid_presence_penalty")
    except RequestError as exc:
        assert exc.code == "invalid_presence_penalty"


def test_http_top_p_and_penalties_accepted() -> None:
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
                    "top_p": 0.8,
                    "presence_penalty": 0.2,
                    "frequency_penalty": 0.1,
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


def test_http_top_p_out_of_range_rejected() -> None:
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
                    "top_p": 2,
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
            assert body["error"]["code"] == "invalid_top_p"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_top_p_and_penalties()
    test_http_top_p_and_penalties_accepted()
    test_http_top_p_out_of_range_rejected()
    print("ok")
