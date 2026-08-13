"""Legacy Completions echo (bool), best_of (int), and suffix (str) validation."""

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
    _validate_completions_echo_best_of_suffix,
    build_server,
)

_TEST_AUTH_TOKEN = "cmpl_fields_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_echo_best_of_suffix() -> None:
    _validate_completions_echo_best_of_suffix({})
    _validate_completions_echo_best_of_suffix({"echo": True, "suffix": "x", "best_of": 2, "n": 1})
    _validate_completions_echo_best_of_suffix({"suffix": None})
    try:
        _validate_completions_echo_best_of_suffix({"echo": "yes"})
        raise AssertionError("expected invalid_echo")
    except RequestError as exc:
        assert exc.code == "invalid_echo"
    try:
        _validate_completions_echo_best_of_suffix({"suffix": 12})
        raise AssertionError("expected invalid_suffix")
    except RequestError as exc:
        assert exc.code == "invalid_suffix"
    try:
        _validate_completions_echo_best_of_suffix({"best_of": 0})
        raise AssertionError("expected invalid_best_of")
    except RequestError as exc:
        assert exc.code == "invalid_best_of"
    try:
        _validate_completions_echo_best_of_suffix({"best_of": 1, "stream": True})
        raise AssertionError("expected invalid_best_of stream")
    except RequestError as exc:
        assert exc.code == "invalid_best_of"
    try:
        _validate_completions_echo_best_of_suffix({"best_of": 1, "n": 3})
        raise AssertionError("expected invalid_best_of n")
    except RequestError as exc:
        assert exc.code == "invalid_best_of"


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


def test_http_rejects_bad_echo_and_best_of() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(port, {"model": "mock-generalist", "prompt": "hi", "echo": 1})
        assert status == 400, body
        assert body["error"]["code"] == "invalid_echo"

        status, body = _post(port, {"model": "mock-generalist", "prompt": "hi", "best_of": 0})
        assert status == 400, body
        assert body["error"]["code"] == "invalid_best_of"

        status, body = _post(
            port, {"model": "mock-generalist", "prompt": "hi", "best_of": 1, "n": 2}
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_best_of"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_valid_echo_suffix_best_of() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "prompt": "hello gateway",
                "echo": False,
                "suffix": "!",
                "best_of": 2,
                "n": 1,
            },
        )
        assert status == 200, body
        assert body["object"] == "text_completion"
        assert isinstance(body["choices"][0]["text"], str)
        assert body["choices"][0]["text"]  # real mock answer non-empty
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_echo_best_of_suffix()
    test_http_rejects_bad_echo_and_best_of()
    test_http_accepts_valid_echo_suffix_best_of()
    print("ok")
