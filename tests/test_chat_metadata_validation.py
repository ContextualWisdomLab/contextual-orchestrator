"""OpenAI chat metadata validation and usage total consistency."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import _normalize_usage, chat_completion_response  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _validate_chat_metadata,
    build_server,
)

_TEST_AUTH_TOKEN = "metadata_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_chat_metadata_accepts_string_map() -> None:
    assert _validate_chat_metadata(None) is None
    assert _validate_chat_metadata({"trace_id": "abc", "team": "ops"}) == {
        "trace_id": "abc",
        "team": "ops",
    }


def test_validate_chat_metadata_rejects_bad_shapes() -> None:
    try:
        _validate_chat_metadata(["not", "object"])
        raise AssertionError("expected invalid_metadata")
    except RequestError as exc:
        assert exc.code == "invalid_metadata"
    try:
        _validate_chat_metadata({"n": 1})
        raise AssertionError("expected invalid_metadata for non-string value")
    except RequestError as exc:
        assert exc.code == "invalid_metadata"
    try:
        _validate_chat_metadata({f"k{i}": "v" for i in range(17)})
        raise AssertionError("expected invalid_metadata for >16 pairs")
    except RequestError as exc:
        assert exc.code == "invalid_metadata"


def test_normalize_usage_fills_total_when_missing() -> None:
    assert _normalize_usage(None) == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert _normalize_usage({"prompt_tokens": 3, "completion_tokens": 5}) == {
        "prompt_tokens": 3,
        "completion_tokens": 5,
        "total_tokens": 8,
    }
    body = chat_completion_response(
        {"answer": "hi", "mode": "route"},
        usage={"prompt_tokens": 2, "completion_tokens": 4},
    )
    assert body["usage"]["total_tokens"] == 6


def test_http_metadata_accepted_and_invalid_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/v1/chat/completions"

    def post(payload: dict) -> tuple[int, dict]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        ok_status, ok_body = post(
            {
                "messages": [{"role": "user", "content": "hello"}],
                "orchestration": "route",
                "metadata": {"trace_id": "run-1", "buyer": "acme"},
            }
        )
        bad_status, bad_body = post(
            {
                "messages": [{"role": "user", "content": "hello"}],
                "metadata": {"count": 3},
            }
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert ok_status == 200, ok_body
    assert ok_body["object"] == "chat.completion"
    assert ok_body["usage"]["total_tokens"] == (
        ok_body["usage"]["prompt_tokens"] + ok_body["usage"]["completion_tokens"]
    )
    assert bad_status == 400
    assert bad_body["error"]["code"] == "invalid_metadata"


if __name__ == "__main__":
    test_validate_chat_metadata_accepts_string_map()
    test_validate_chat_metadata_rejects_bad_shapes()
    test_normalize_usage_fills_total_when_missing()
    test_http_metadata_accepted_and_invalid_rejected()
    print("ok")
