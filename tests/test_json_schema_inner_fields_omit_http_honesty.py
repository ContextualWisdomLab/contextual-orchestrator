"""response_format.json_schema inner fields are omit-real over HTTP.

OpenAI structured-output objects accept optional ``description`` and
``strict`` on ``response_format.json_schema``. Official SDKs serialize
omitted optionals as JSON null or empty string. Accepting those keys
without popping them is not omit-equivalent: ``proxy_completion``
forwards the body, and several providers reject ``strict: null`` or a
null ``description``.

These cases assert the buyer-visible contract:

* chat and Responses return 200
* mock ``echo.response_format.json_schema`` no longer contains null or
  blank optional keys
* unknown inner keys and non-string descriptions stay fail-closed
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
    _validate_chat_response_format,
    build_server,
)

_TEST_AUTH_TOKEN = "json_schema_inner_fields_omit_http_honesty_token"  # noqa: S105

_SCHEMA_BODY = {
    "type": "object",
    "properties": {"amount": {"type": "number"}},
}


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


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


def _echo_schema(body: dict) -> dict:
    echo = body.get("echo") or {}
    fmt = echo.get("response_format") or {}
    schema = fmt.get("json_schema")
    assert isinstance(schema, dict), body
    return schema


def _json_schema_payload(inner: dict) -> dict:
    return {
        "type": "json_schema",
        "json_schema": inner,
    }


def test_validate_chat_response_format_pops_null_and_blank_inner_fields() -> None:
    body = {
        "response_format": _json_schema_payload(
            {
                "name": "receipt_line",
                "description": None,
                "schema": _SCHEMA_BODY,
                "strict": None,
            }
        )
    }
    validated = _validate_chat_response_format(body)
    assert validated is not None
    schema = validated["json_schema"]
    assert "description" not in schema
    assert "strict" not in schema
    assert schema.get("name") == "receipt_line"
    assert "description" not in body["response_format"]["json_schema"]
    assert "strict" not in body["response_format"]["json_schema"]

    blank = {
        "response_format": _json_schema_payload(
            {
                "name": "receipt_line",
                "description": "  \u00a0  ",
                "schema": _SCHEMA_BODY,
                "strict": False,
            }
        )
    }
    validated_blank = _validate_chat_response_format(blank)
    assert validated_blank is not None
    assert "description" not in validated_blank["json_schema"]
    assert validated_blank["json_schema"].get("strict") is False


def test_http_chat_omits_json_schema_strict_null() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "strict null"}],
                "response_format": _json_schema_payload(
                    {
                        "name": "receipt_line",
                        "schema": _SCHEMA_BODY,
                        "strict": None,
                    }
                ),
            },
        )
        assert status == 200, body
        schema = _echo_schema(body)
        assert "strict" not in schema
        assert schema.get("name") == "receipt_line"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_omits_json_schema_description_null_and_blank() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "desc null"}],
                "response_format": _json_schema_payload(
                    {
                        "name": "receipt_line",
                        "description": None,
                        "schema": _SCHEMA_BODY,
                        "strict": True,
                    }
                ),
            },
        )
        assert status == 200, body
        schema = _echo_schema(body)
        assert "description" not in schema
        assert schema.get("strict") is True

        status_blank, body_blank = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "desc blank"}],
                "response_format": _json_schema_payload(
                    {
                        "name": "receipt_line",
                        "description": "   ",
                        "schema": _SCHEMA_BODY,
                    }
                ),
            },
        )
        assert status_blank == 200, body_blank
        assert "description" not in _echo_schema(body_blank)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_omits_json_schema_null_inner_fields() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "responses json_schema nulls",
                "response_format": _json_schema_payload(
                    {
                        "name": "receipt_line",
                        "description": None,
                        "schema": _SCHEMA_BODY,
                        "strict": None,
                    }
                ),
            },
        )
        assert status == 200, body
        schema = _echo_schema(body)
        assert "description" not in schema
        assert "strict" not in schema
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_json_schema_unknown_inner_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "unknown inner"}],
                "response_format": _json_schema_payload(
                    {
                        "name": "receipt_line",
                        "schema": _SCHEMA_BODY,
                        "additionalProperties": False,
                    }
                ),
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_response_format" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_json_schema_description_non_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "desc bad"}],
                "response_format": _json_schema_payload(
                    {
                        "name": "receipt_line",
                        "description": 123,
                        "schema": _SCHEMA_BODY,
                    }
                ),
            },
        )
        assert status == 400, body
        assert "invalid_response_format" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_keeps_non_null_json_schema_inner_fields() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "keep fields"}],
                "response_format": _json_schema_payload(
                    {
                        "name": "receipt_line",
                        "description": "one receipt line",
                        "schema": _SCHEMA_BODY,
                        "strict": True,
                    }
                ),
            },
        )
        assert status == 200, body
        schema = _echo_schema(body)
        assert schema.get("description") == "one receipt line"
        assert schema.get("strict") is True
        assert schema.get("schema") == _SCHEMA_BODY
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_chat_response_format_pops_null_and_blank_inner_fields()
    test_http_chat_omits_json_schema_strict_null()
    test_http_chat_omits_json_schema_description_null_and_blank()
    test_http_responses_omits_json_schema_null_inner_fields()
    test_http_chat_rejects_json_schema_unknown_inner_key()
    test_http_chat_rejects_json_schema_description_non_string()
    test_http_chat_keeps_non_null_json_schema_inner_fields()
    print("ok")
