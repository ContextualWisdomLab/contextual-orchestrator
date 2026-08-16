"""Official Responses ``text.format`` is omit-real over HTTP.

OpenAI Responses structured output lives on ``text.format``, not chat
``response_format``. Official SDKs send a flat format object
(``type`` / ``name`` / ``schema`` / ``description`` / ``strict``).
Rejecting every non-empty ``text`` with ``invalid_text`` is a buyer-visible
gap: the official Python/JS Responses client never reaches the provider.

These cases assert the buyer-visible contract:

* ``text.format`` type ``text`` / ``json_object`` / ``json_schema`` return 200
* mock ``echo.text.format`` no longer contains null or blank optionals
* unknown format keys, missing schema, and non-string description stay
  fail-closed with named ``invalid_text``
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
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "responses_text_format_http_honesty_token"  # noqa: S105

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
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _echo_format(body: dict) -> dict:
    echo = body.get("echo") or {}
    text = echo.get("text") or {}
    fmt = text.get("format")
    assert isinstance(fmt, dict), body
    return fmt


def test_http_responses_accepts_official_text_format_type_text() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "official text format",
                "text": {"format": {"type": "text"}},
            },
        )
        assert status == 200, body
        assert _echo_format(body) == {"type": "text"}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_official_json_schema_text_format() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "official json_schema format",
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "item_schema",
                        "schema": _SCHEMA_BODY,
                    }
                },
            },
        )
        assert status == 200, body
        fmt = _echo_format(body)
        assert fmt["type"] == "json_schema"
        assert fmt["name"] == "item_schema"
        assert fmt["schema"] == _SCHEMA_BODY
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_omits_null_and_blank_text_format_optionals() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "null text.format optionals",
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "item_schema",
                        "description": None,
                        "schema": _SCHEMA_BODY,
                        "strict": None,
                    }
                },
            },
        )
        assert status == 200, body
        fmt = _echo_format(body)
        assert "description" not in fmt
        assert "strict" not in fmt
        status_blank, body_blank = _post(
            port,
            {
                "model": "mock-planner",
                "input": "blank text.format description",
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "item_schema",
                        "description": "   ",
                        "schema": _SCHEMA_BODY,
                        "strict": False,
                    }
                },
            },
        )
        assert status_blank == 200, body_blank
        fmt_blank = _echo_format(body_blank)
        assert "description" not in fmt_blank
        assert fmt_blank.get("strict") is False
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
                "text": {"format": {"type": "json_object", "pretty": True}},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_text" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_json_schema_text_format_without_schema() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "missing schema",
                "text": {"format": {"type": "json_schema", "name": "item_schema"}},
            },
        )
        assert status == 400, body
        assert "invalid_text" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_unknown_text_sibling() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "unknown text sibling",
                "text": {"prompt": "not a format object"},
            },
        )
        assert status == 400, body
        assert "invalid_text" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_accepts_official_text_format_type_text()
    test_http_responses_accepts_official_json_schema_text_format()
    test_http_responses_omits_null_and_blank_text_format_optionals()
    test_http_responses_rejects_unknown_text_format_key()
    test_http_responses_rejects_json_schema_text_format_without_schema()
    test_http_responses_rejects_unknown_text_sibling()
    print("ok")
