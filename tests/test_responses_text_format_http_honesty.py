"""Responses official ``text.format`` honesty over HTTP.

OpenAI SDKs send ``text: {format: {type: "text"}}`` as the default output
control. After that default is accepted, the remaining buyer-visible holes
are structured ``text.format`` types, omit-real optionals, ``verbosity``,
and dual-plane ``text`` + ``response_format``.
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
    _validate_responses_text,
    build_server,
)

_TEST_AUTH_TOKEN = "responses_text_format_http_honesty_token"  # noqa: S105

_OFFICIAL_TEXT_FORMAT = {"format": {"type": "text"}}
_SCHEMA_BODY = {
    "type": "object",
    "properties": {"amount": {"type": "number"}},
}


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


def test_validate_responses_text_pops_null_json_schema_optionals() -> None:
    """Null/blank json_schema optionals and verbosity must be omit-real in place."""
    body = {
        "text": {
            "format": {
                "type": "json_schema",
                "name": "receipt_line",
                "description": None,
                "schema": _SCHEMA_BODY,
                "strict": None,
            },
            "verbosity": None,
        }
    }
    validated = _validate_responses_text(body)
    assert validated is not None
    fmt = validated["format"]
    assert "description" not in fmt
    assert "strict" not in fmt
    assert "verbosity" not in validated
    assert fmt.get("name") == "receipt_line"
    assert "description" not in body["text"]["format"]
    assert "strict" not in body["text"]["format"]


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


def test_http_responses_accepts_text_format_json_object() -> None:
    """Official text.format.type=json_object must forward, not 400 invalid_text."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "return a json object",
                "text": {"format": {"type": "json_object"}},
            },
        )
        assert status == 200, body
        assert body.get("echo", {}).get("text") == {"format": {"type": "json_object"}}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_omits_json_schema_null_optionals_on_text_format() -> None:
    """Flat text.format json_schema must pop null/blank optionals before echo."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "text.format json_schema nulls",
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "receipt_line",
                        "description": "  ",
                        "schema": _SCHEMA_BODY,
                        "strict": None,
                    }
                },
            },
        )
        assert status == 200, body
        fmt = (body.get("echo") or {}).get("text", {}).get("format")
        assert isinstance(fmt, dict), body
        assert "description" not in fmt
        assert "strict" not in fmt
        assert fmt.get("name") == "receipt_line"
        assert fmt.get("schema") == _SCHEMA_BODY
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_text_verbosity() -> None:
    """Known text.verbosity levels are default-length no-ops."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "verbosity noop",
                "text": {"format": {"type": "text"}, "verbosity": "high"},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_unknown_text_format_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "unknown format key",
                "text": {"format": {"type": "text", "name": "smuggle"}},
            },
        )
        assert status == 400, body
        assert "invalid_text" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_text_plus_response_format() -> None:
    """Accepting official type=text must not open a dual-plane passthrough."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "two structured-output planes",
                "text": {"format": {"type": "text"}},
                "response_format": {"type": "json_object"},
            },
        )
        assert status == 400, body
        assert "invalid_text" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_responses_text_pops_null_json_schema_optionals()
    test_official_text_format_is_not_rejected_by_validator()
    test_http_responses_accepts_official_text_format()
    test_http_responses_rejects_unknown_text_format_type()
    test_http_responses_accepts_text_format_json_object()
    test_http_responses_omits_json_schema_null_optionals_on_text_format()
    test_http_responses_accepts_text_verbosity()
    test_http_responses_rejects_unknown_text_format_key()
    test_http_responses_rejects_text_plus_response_format()
    print("ok")
