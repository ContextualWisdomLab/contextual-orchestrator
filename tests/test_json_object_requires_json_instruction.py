"""response_format json_object requires a prompt that mentions JSON."""

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
    _validate_json_object_requires_json_instruction,
    build_server,
)

_TEST_AUTH_TOKEN = "json_obj_instr_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_json_object_requires_json_instruction() -> None:
    _validate_json_object_requires_json_instruction({})
    _validate_json_object_requires_json_instruction(
        {"response_format": {"type": "text"}}
    )
    _validate_json_object_requires_json_instruction(
        {
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": "Reply as JSON only"}],
        }
    )
    try:
        _validate_json_object_requires_json_instruction(
            {
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": "hello"}],
            }
        )
        raise AssertionError("expected invalid_response_format")
    except RequestError as exc:
        assert exc.code == "invalid_response_format"
    # Responses-style input
    _validate_json_object_requires_json_instruction(
        {
            "response_format": {"type": "json_object"},
            "input": "Emit a JSON object with field ok",
        }
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
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


def test_http_rejects_json_object_without_instruction() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "say hi"}],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_response_format"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_accepts_json_object_with_instruction() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            {
                "model": "mock-generalist",
                "messages": [
                    {"role": "system", "content": "You always answer in JSON."},
                    {"role": "user", "content": "status?"},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 200, body
        assert body["choices"][0]["message"]["content"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_json_object_requires_json_instruction()
    test_http_rejects_json_object_without_instruction()
    test_http_accepts_json_object_with_instruction()
    print("ok")
