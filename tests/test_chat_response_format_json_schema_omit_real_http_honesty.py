"""Chat response_format.json_schema omit-real + unknown-key honesty over HTTP."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    SecurityConfig,
    build_server,
    _validate_chat_response_format,
)

_TEST_AUTH_TOKEN = "chat_rf_json_schema_omit_real_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
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


def _post_responses(port: int, payload: dict) -> tuple[int, dict]:
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


def test_validate_chat_response_format_pops_null_json_schema_optionals() -> None:
    """Null/blank nested optionals must be omit-real in place before proxy."""
    body = {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "receipt_line",
                "schema": {"type": "object"},
                "description": None,
                "strict": None,
            },
        }
    }
    fmt = _validate_chat_response_format(body)
    assert fmt is not None
    schema = fmt["json_schema"]
    assert "description" not in schema
    assert "strict" not in schema
    # Mutates the request body so passthrough matches omit.
    assert "description" not in body["response_format"]["json_schema"]
    assert "strict" not in body["response_format"]["json_schema"]

    body_blank = {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "receipt_line",
                "schema": {"type": "object"},
                "description": "  ",
            },
        }
    }
    fmt_blank = _validate_chat_response_format(body_blank)
    assert fmt_blank is not None
    assert "description" not in fmt_blank["json_schema"]


def test_validate_chat_response_format_rejects_unknown_json_schema_keys() -> None:
    body = {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "receipt_line",
                "schema": {"type": "object"},
                "foo": 1,
            },
        }
    }
    try:
        _validate_chat_response_format(body)
        raise AssertionError("expected RequestError for unknown nested key")
    except Exception as exc:
        assert getattr(exc, "code", None) == "invalid_response_format"
        msg = getattr(exc, "message", str(exc))
        assert "name, schema" in msg


def test_http_chat_omits_json_schema_null_optionals_on_response_format() -> None:
    """Nested null/blank optionals must not break structured-output chat."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "rf json_schema null optionals"}
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "receipt_line",
                        "schema": {
                            "type": "object",
                            "properties": {"amount": {"type": "number"}},
                        },
                        "description": "  ",
                        "strict": None,
                    },
                },
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "response_format",
    [
        {"type": "json_object"},
        {
            "type": "json_schema",
            "json_schema": {
                "name": "receipt_line",
                "schema": {
                    "type": "object",
                    "properties": {"amount": {"type": "number"}},
                },
            },
        },
    ],
)
def test_http_chat_structured_output_keeps_multi_agent_workflow(response_format: dict) -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "structured workflow"}],
                "response_format": response_format,
            },
        )
        assert status == 200, body
        assert body["orchestration"]["mode"] == "conduct"
        assert body["orchestration"]["channel"] == "sync"
        assert body["orchestration"]["workflow_run_id"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_json_schema_keeps_multi_agent_workflow() -> None:
    server, thread, port = _server()
    try:
        status, body = _post_responses(
            port,
            {
                "model": "mock-planner",
                "input": "structured responses workflow",
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "receipt_line",
                        "schema": {
                            "type": "object",
                            "properties": {"amount": {"type": "number"}},
                        },
                    }
                },
            },
        )
        assert status == 200, body
        assert body["orchestration"]["mode"] == "conduct"
        assert body["orchestration"]["channel"] == "sync"
        assert body["orchestration"]["workflow_run_id"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_json_schema_nested_key() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "unknown nested"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "receipt_line",
                        "schema": {"type": "object"},
                        "additional_properties": False,
                    },
                },
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_response_format" in blob
        assert "unknown_fields" not in blob
        assert "name, schema" in blob or "description" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_non_string_json_schema_description() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "bad description type"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "receipt_line",
                        "schema": {"type": "object"},
                        "description": 12,
                    },
                },
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_response_format" in blob
        assert "description" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_omits_json_schema_null_optionals_on_response_format() -> None:
    """Responses path reuses chat response_format validator — same omit-real."""
    server, thread, port = _server()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/responses",
            data=json.dumps(
                {
                    "model": "mock-planner",
                    "input": "rf json_schema nulls on responses",
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "item_schema",
                            "schema": {"type": "object"},
                            "description": None,
                            "strict": None,
                        },
                    },
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status = response.status
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_chat_response_format_pops_null_json_schema_optionals()
    test_validate_chat_response_format_rejects_unknown_json_schema_keys()
    test_http_chat_omits_json_schema_null_optionals_on_response_format()
    test_http_chat_rejects_unknown_json_schema_nested_key()
    test_http_chat_rejects_non_string_json_schema_description()
    test_http_responses_omits_json_schema_null_optionals_on_response_format()
    print("ok")
