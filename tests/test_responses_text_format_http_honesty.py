"""Official Responses ``text.format`` is omit-real over HTTP.

The OpenAI Responses SDK sends ``text: {format: {type: text}}`` as the
default structured-output plane. Rejecting that object as unsupported
breaks every official-SDK caller. Accept the documented ``format``
shapes, pop JSON-null / blank optionals so proxy matches omit, and
fail closed on unknown keys or ``verbosity`` (this gateway does not
apply verbosity).

These cases assert the buyer-visible contract:

* ``text.format.type=text`` / ``json_object`` return 200
* ``text.format`` json_schema pops null/blank ``description`` and null
  ``strict``; mock ``echo.text`` no longer contains those keys
* unknown ``text`` / ``format`` keys and ``verbosity`` stay ``invalid_text``
* ``response_format`` plus non-omit ``text`` stay fail-closed
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
    _validate_responses_text,
    build_server,
)

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


def _echo_text(body: dict) -> dict:
    echo = body.get("echo") or {}
    text = echo.get("text")
    assert isinstance(text, dict), body
    return text


def test_validate_responses_text_pops_null_json_schema_optionals() -> None:
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


def test_http_responses_accepts_official_text_format_type_text() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "official sdk default",
                "text": {"format": {"type": "text"}},
            },
        )
        assert status == 200, body
        text = _echo_text(body)
        assert text.get("format") == {"type": "text"}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_omits_json_schema_null_optionals_on_text_format() -> None:
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
        fmt = _echo_text(body).get("format")
        assert isinstance(fmt, dict), body
        assert "description" not in fmt
        assert "strict" not in fmt
        assert fmt.get("name") == "receipt_line"
        assert fmt.get("schema") == _SCHEMA_BODY
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_text_verbosity() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "verbosity not applied",
                "text": {"format": {"type": "text"}, "verbosity": "high"},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_text" in blob
        assert "unknown_fields" not in blob
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
    test_http_responses_accepts_official_text_format_type_text()
    test_http_responses_omits_json_schema_null_optionals_on_text_format()
    test_http_responses_rejects_text_verbosity()
    test_http_responses_rejects_unknown_text_format_key()
    test_http_responses_rejects_text_plus_response_format()
    print("ok")
