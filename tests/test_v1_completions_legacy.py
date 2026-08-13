"""OpenAI-compatible legacy POST /v1/completions (prompt → text_completion)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.api_contract import OPENAPI_SPEC  # noqa: E402
from contextual_orchestrator.orchestrator import text_completion_response  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "completions_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def post_json(url: str, payload: dict) -> tuple[int, dict]:
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


def test_text_completion_response_shape() -> None:
    body = text_completion_response(
        {"answer": "hello world", "mode": "route", "workflow_run_id": "run_1"},
        model="mock-generalist",
        usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    )
    assert body["object"] == "text_completion"
    assert body["id"].startswith("cmpl-")
    assert body["choices"][0]["text"] == "hello world"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["total_tokens"] == 5


def test_http_completions_returns_text_completion() -> None:
    """Buyer path: older OpenAI clients send prompt, not messages."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = post_json(
            f"http://127.0.0.1:{port}/v1/completions",
            {"model": "mock-generalist", "prompt": "Complete this sentence about systems."},
        )
        status_list, body_list = post_json(
            f"http://127.0.0.1:{port}/v1/completions",
            {"prompt": ["line one", "line two"]},
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    assert body["object"] == "text_completion"
    assert body["model"] == "mock-generalist"
    assert isinstance(body["choices"][0]["text"], str)
    assert body["choices"][0]["text"]
    assert status_list == 200, body_list
    assert body_list["object"] == "text_completion"


def test_http_completions_rejects_empty_prompt_and_stream() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        empty_status, empty_body = post_json(
            f"http://127.0.0.1:{port}/v1/completions",
            {"prompt": ""},
        )
        stream_status, stream_body = post_json(
            f"http://127.0.0.1:{port}/v1/completions",
            {"prompt": "hi", "stream": True},
        )
        n_status, n_body = post_json(
            f"http://127.0.0.1:{port}/v1/completions",
            {"prompt": "hi", "n": 2},
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert empty_status == 400
    assert empty_body["error"]["code"] == "invalid_prompt"
    assert stream_status == 400
    assert stream_body["error"]["code"] == "invalid_request"
    assert n_status == 400
    assert n_body["error"]["code"] == "invalid_n"


def test_openapi_includes_v1_completions() -> None:
    assert "/v1/completions" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/v1/completions"]["post"]["operationId"] == "create_text_completion"


if __name__ == "__main__":
    test_text_completion_response_shape()
    test_http_completions_returns_text_completion()
    test_http_completions_rejects_empty_prompt_and_stream()
    test_openapi_includes_v1_completions()
    print("ok")
