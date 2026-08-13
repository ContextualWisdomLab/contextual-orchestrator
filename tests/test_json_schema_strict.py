"""OpenAI response_format.json_schema.strict boolean validation."""

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
    _validate_response_format_strict,
    build_server,
)

_TEST_AUTH_TOKEN = "strict_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_strict() -> None:
    assert _validate_response_format_strict({}) is None
    good = {
        "type": "json_schema",
        "json_schema": {"name": "out", "strict": True, "schema": {"type": "object"}},
    }
    assert _validate_response_format_strict({"response_format": good}) == good
    try:
        _validate_response_format_strict(
            {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "out", "strict": "yes"},
                }
            }
        )
        raise AssertionError("expected invalid_response_format")
    except RequestError as exc:
        assert exc.code == "invalid_response_format"


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
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


def test_http_chat_accepts_strict_true() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "hi"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "reply",
                        "strict": True,
                        "schema": {"type": "object"},
                    },
                },
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_non_bool_strict() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-generalist",
                "input": "hi",
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "reply", "strict": 1},
                },
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_response_format"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_strict()
    test_http_chat_accepts_strict_true()
    test_http_responses_rejects_non_bool_strict()
    print("ok")
