"""OpenAI Responses API input and instructions validation on /v1/responses."""

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
    _validate_responses_input,
    _validate_responses_instructions,
    build_server,
)

_TEST_AUTH_TOKEN = "resp_input_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_responses_input() -> None:
    assert _validate_responses_input({"input": "hello"}) == "hello"
    assert _validate_responses_input({"input": ["a", "b"]}) == ["a", "b"]
    assert _validate_responses_input({"input": [{"role": "user", "content": "hi"}]})[0]["role"] == "user"
    try:
        _validate_responses_input({})
        raise AssertionError("missing")
    except RequestError as exc:
        assert exc.code == "invalid_input"
    try:
        _validate_responses_input({"input": ""})
        raise AssertionError("empty string")
    except RequestError as exc:
        assert exc.code == "invalid_input"
    try:
        _validate_responses_input({"input": []})
        raise AssertionError("empty array")
    except RequestError as exc:
        assert exc.code == "invalid_input"
    try:
        _validate_responses_input({"input": 1})
        raise AssertionError("bad type")
    except RequestError as exc:
        assert exc.code == "invalid_input"


def test_validate_responses_instructions() -> None:
    assert _validate_responses_instructions({}) is None
    assert _validate_responses_instructions({"instructions": "Be brief."}) == "Be brief."
    try:
        _validate_responses_instructions({"instructions": ""})
        raise AssertionError("empty")
    except RequestError as exc:
        assert exc.code == "invalid_instructions"
    try:
        _validate_responses_instructions({"instructions": 1})
        raise AssertionError("non-string")
    except RequestError as exc:
        assert exc.code == "invalid_instructions"


def test_http_responses_input_accepted() -> None:
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
                    "input": "what is 2+2?",
                    "instructions": "Answer with a single digit.",
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
    assert body.get("object") in {"response", "chat.completion"} or "output" in body or "choices" in body


def test_http_responses_missing_input_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/responses",
            data=json.dumps({"model": "mock-generalist"}).encode("utf-8"),
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
            assert body["error"]["code"] == "invalid_input"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_responses_input()
    test_validate_responses_instructions()
    test_http_responses_input_accepted()
    test_http_responses_missing_input_rejected()
    print("ok")
