"""Responses official ``text.format`` honesty over HTTP.

OpenAI SDKs send ``text: {format: {type: "text"}}`` as the default output
control. Rejecting that official default as ``invalid_text`` is a buyer-facing
gap: the same gateway already accepts ``response_format: {type: "text"}``.
"""

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
    SecurityConfig,
    _validate_responses_conversation_controls,
    build_server,
)

_TEST_AUTH_TOKEN = "responses_text_format_http_honesty_token"  # noqa: S105

_OFFICIAL_TEXT_FORMAT = {"format": {"type": "text"}}


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
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


def test_official_text_format_is_not_rejected_by_validator() -> None:
    """SDK default text.format.type=text must not raise invalid_text."""
    body = {
        "model": "mock-planner",
        "input": "summarize the ledger",
        "text": dict(_OFFICIAL_TEXT_FORMAT),
    }
    _validate_responses_conversation_controls(body)
    assert body["text"] == _OFFICIAL_TEXT_FORMAT


def test_http_responses_accepts_official_text_format() -> None:
    """Live /v1/responses must forward the official default, not 400 invalid_text."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "summarize the ledger",
                "text": dict(_OFFICIAL_TEXT_FORMAT),
            },
        )
        assert status == 200, body
        assert body.get("echo", {}).get("text") == _OFFICIAL_TEXT_FORMAT
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_unknown_text_format_type() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "summarize the ledger",
                "text": {"format": {"type": "xml"}},
            },
        )
        assert status == 400, body
        assert "invalid_text" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_official_text_format_is_not_rejected_by_validator()
    test_http_responses_accepts_official_text_format()
    test_http_responses_rejects_unknown_text_format_type()
    print("ok")
