"""OpenAI Responses API reasoning object validation."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _validate_responses_reasoning,
    build_server,
)

_TEST_AUTH_TOKEN = "responses_reason_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_responses_reasoning() -> None:
    assert _validate_responses_reasoning({}) is None
    assert _validate_responses_reasoning({"reasoning": {}}) == {}
    assert _validate_responses_reasoning(
        {"reasoning": {"effort": "low", "summary": "auto", "mode": "pro", "context": "all_turns"}}
    ) == {"effort": "low", "summary": "auto", "mode": "pro", "context": "all_turns"}
    assert _validate_responses_reasoning({"reasoning": {"effort": "xhigh"}})["effort"] == "xhigh"
    assert _validate_responses_reasoning({"reasoning": {"effort": "none"}})["effort"] == "none"
    try:
        _validate_responses_reasoning({"reasoning": "low"})
        raise AssertionError("non-object")
    except RequestError as exc:
        assert exc.code == "invalid_reasoning"
    try:
        _validate_responses_reasoning({"reasoning": {"effort": "ultra"}})
        raise AssertionError("bad effort")
    except RequestError as exc:
        assert exc.code == "invalid_reasoning"
    try:
        _validate_responses_reasoning({"reasoning": {"summary": "verbose"}})
        raise AssertionError("bad summary")
    except RequestError as exc:
        assert exc.code == "invalid_reasoning"
    try:
        _validate_responses_reasoning({"reasoning": {"mode": "turbo"}})
        raise AssertionError("bad mode")
    except RequestError as exc:
        assert exc.code == "invalid_reasoning"
    try:
        _validate_responses_reasoning({"reasoning": {"context": "previous"}})
        raise AssertionError("bad context")
    except RequestError as exc:
        assert exc.code == "invalid_reasoning"
    try:
        _validate_responses_reasoning({"reasoning": {"effort": "low", "generate_summary": True}})
        raise AssertionError("unknown key")
    except RequestError as exc:
        assert exc.code == "invalid_reasoning"
        assert "generate_summary" in exc.detail.get("fields", [])


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
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_responses_reasoning_accepted() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "input": "summarize",
                "reasoning": {"effort": "medium", "summary": "auto"},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 200
    assert body["object"] == "response"
    assert body["output"][0]["role"] == "assistant"


def test_http_invalid_reasoning_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "input": "summarize",
                "reasoning": {"effort": "ludicrous"},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 400
    assert body["error"]["code"] == "invalid_reasoning"


if __name__ == "__main__":
    test_validate_responses_reasoning()
    test_http_responses_reasoning_accepted()
    test_http_invalid_reasoning_rejected()
    print("ok")
