"""OpenAI Responses max_output_tokens, previous_response_id, truncation, text."""

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
    _validate_responses_max_output_tokens,
    _validate_responses_previous_response_id,
    _validate_responses_text,
    _validate_responses_truncation,
    build_server,
)

_TEST_AUTH_TOKEN = "resp_max_out_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_responses_max_output_tokens() -> None:
    assert _validate_responses_max_output_tokens({}) is None
    assert _validate_responses_max_output_tokens({"max_output_tokens": 128}) == 128
    try:
        _validate_responses_max_output_tokens({"max_output_tokens": 0})
        raise AssertionError("zero")
    except RequestError as exc:
        assert exc.code == "invalid_max_output_tokens"
    try:
        _validate_responses_max_output_tokens({"max_output_tokens": True})
        raise AssertionError("bool")
    except RequestError as exc:
        assert exc.code == "invalid_max_output_tokens"
    try:
        _validate_responses_max_output_tokens({"max_output_tokens": 1.5})
        raise AssertionError("float")
    except RequestError as exc:
        assert exc.code == "invalid_max_output_tokens"


def test_validate_previous_response_id_truncation_text() -> None:
    assert _validate_responses_previous_response_id({}) is None
    assert (
        _validate_responses_previous_response_id({"previous_response_id": "resp_abc"})
        == "resp_abc"
    )
    try:
        _validate_responses_previous_response_id({"previous_response_id": "  "})
        raise AssertionError("blank")
    except RequestError as exc:
        assert exc.code == "invalid_previous_response_id"
    assert _validate_responses_truncation({"truncation": "auto"}) == "auto"
    assert _validate_responses_truncation({"truncation": "disabled"}) == "disabled"
    try:
        _validate_responses_truncation({"truncation": "hard"})
        raise AssertionError("bad truncation")
    except RequestError as exc:
        assert exc.code == "invalid_truncation"
    assert _validate_responses_text({"text": {"format": {"type": "text"}}}) == {
        "format": {"type": "text"}
    }
    assert _validate_responses_text({"text": {"verbosity": "low"}}) == {"verbosity": "low"}
    try:
        _validate_responses_text({"text": "plain"})
        raise AssertionError("string text")
    except RequestError as exc:
        assert exc.code == "invalid_text"
    try:
        _validate_responses_text({"text": {"unknown_key": 1}})
        raise AssertionError("unknown")
    except RequestError as exc:
        assert exc.code == "invalid_text"


def _post_responses(port: int, payload: dict) -> tuple[int, dict]:
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


def test_http_responses_accepts_max_output_and_text() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post_responses(
            port,
            {
                "model": "mock-generalist",
                "input": "hello",
                "max_output_tokens": 64,
                "previous_response_id": "resp_prev",
                "truncation": "auto",
                "text": {"format": {"type": "text"}, "verbosity": "medium"},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_bad_max_output_tokens() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post_responses(
            port,
            {
                "model": "mock-generalist",
                "input": "hello",
                "max_output_tokens": 0,
            },
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_max_output_tokens"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_unknown_text_field() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post_responses(
            port,
            {
                "model": "mock-generalist",
                "input": "hello",
                "text": {"format": {"type": "text"}, "bogus": True},
            },
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_text"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_responses_max_output_tokens()
    test_validate_previous_response_id_truncation_text()
    test_http_responses_accepts_max_output_and_text()
    test_http_responses_rejects_bad_max_output_tokens()
    test_http_responses_rejects_unknown_text_field()
    print("ok")
