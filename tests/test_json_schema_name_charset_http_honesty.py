"""response_format.json_schema.name charset/length is fail-closed over HTTP.

OpenAI Structured Outputs require ``json_schema.name`` to match
``[a-zA-Z0-9_-]{1,64}`` — the same charset already enforced on
``tool.function.name``. Accepting spaces, punctuation, or names longer
than 64 is not honest: ``proxy_completion`` forwards the body and the
buyer sees an opaque provider rejection instead of a named
``invalid_response_format`` next action.

These cases assert the buyer-visible contract:

* chat and Responses return 400 ``invalid_response_format`` for illegal names
* Unicode letters/digits (``café``, ``名前``, Arabic-Indic digits) fail closed
* a 64-character legal name is kept on mock ``echo.response_format``
* a legal short name is unchanged
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

_TEST_AUTH_TOKEN = "json_schema_name_charset_http_honesty_token"  # noqa: S105

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


def test_validate_chat_response_format_rejects_spaced_json_schema_name() -> None:
    body = {
        "response_format": _json_schema_payload(
            {
                "name": "receipt line",
                "schema": _SCHEMA_BODY,
            }
        )
    }
    try:
        _validate_chat_response_format(body)
    except Exception as exc:
        assert getattr(exc, "code", None) == "invalid_response_format"
        assert "must match [a-zA-Z0-9_-]" in str(exc)
        return
    raise AssertionError("spaced json_schema.name must fail closed")


def test_validate_chat_response_format_rejects_overlong_json_schema_name() -> None:
    body = {
        "response_format": _json_schema_payload(
            {
                "name": "a" * 65,
                "schema": _SCHEMA_BODY,
            }
        )
    }
    try:
        _validate_chat_response_format(body)
    except Exception as exc:
        assert getattr(exc, "code", None) == "invalid_response_format"
        assert "at most 64 characters" in str(exc)
        return
    raise AssertionError("65-character json_schema.name must fail closed")


def test_http_chat_rejects_punctuated_json_schema_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "name punct"}],
                "response_format": _json_schema_payload(
                    {
                        "name": "receipt.line",
                        "schema": _SCHEMA_BODY,
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


def test_http_responses_rejects_overlong_json_schema_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "responses name too long",
                "response_format": _json_schema_payload(
                    {
                        "name": "n" * 65,
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


def test_validate_chat_response_format_rejects_unicode_json_schema_name() -> None:
    """Python str.isalnum() accepts café/名前/١٢٣; OpenAI does not."""
    for illegal_name in ("café", "名前", "schema_١٢٣"):
        body = {
            "response_format": _json_schema_payload(
                {
                    "name": illegal_name,
                    "schema": _SCHEMA_BODY,
                }
            )
        }
        try:
            _validate_chat_response_format(body)
        except Exception as exc:
            assert getattr(exc, "code", None) == "invalid_response_format"
            assert "must match [a-zA-Z0-9_-]" in str(exc)
            continue
        raise AssertionError(f"{illegal_name!r} json_schema.name must fail closed")


def test_http_chat_rejects_unicode_json_schema_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "name unicode"}],
                "response_format": _json_schema_payload(
                    {
                        "name": "café",
                        "schema": _SCHEMA_BODY,
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


def test_http_responses_rejects_unicode_json_schema_name() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "responses name unicode",
                "response_format": _json_schema_payload(
                    {
                        "name": "名前",
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


def test_http_responses_keeps_legal_json_schema_name() -> None:
    server, thread, port = _server()
    try:
        max_name = "B" * 64
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "responses name max",
                "response_format": _json_schema_payload(
                    {
                        "name": max_name,
                        "schema": _SCHEMA_BODY,
                    }
                ),
            },
        )
        assert status == 200, body
        assert _echo_schema(body).get("name") == max_name
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_keeps_legal_json_schema_name() -> None:
    server, thread, port = _server()
    try:
        legal_name = "receipt_line-01"
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "name keep"}],
                "response_format": _json_schema_payload(
                    {
                        "name": legal_name,
                        "schema": _SCHEMA_BODY,
                    }
                ),
            },
        )
        assert status == 200, body
        assert body["object"] == "chat.completion"

        max_name = "A" * 64
        status_max, body_max = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "name max"}],
                "response_format": _json_schema_payload(
                    {
                        "name": max_name,
                        "schema": _SCHEMA_BODY,
                    }
                ),
            },
        )
        assert status_max == 200, body_max
        assert body_max["object"] == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_chat_response_format_rejects_spaced_json_schema_name()
    test_validate_chat_response_format_rejects_overlong_json_schema_name()
    test_validate_chat_response_format_rejects_unicode_json_schema_name()
    test_http_chat_rejects_punctuated_json_schema_name()
    test_http_responses_rejects_overlong_json_schema_name()
    test_http_chat_rejects_unicode_json_schema_name()
    test_http_responses_rejects_unicode_json_schema_name()
    test_http_responses_keeps_legal_json_schema_name()
    test_http_chat_keeps_legal_json_schema_name()
    print("ok")
