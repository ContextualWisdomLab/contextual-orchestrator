"""Responses response_format shape honesty over HTTP (fail-closed)."""

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

_TEST_AUTH_TOKEN = "responses_response_format_http_honesty_token"  # noqa: S105


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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_responses_accepts_text_and_json_object_format() -> None:
    server, thread, port = _server()
    try:
        for fmt in ({"type": "text"}, {"type": "json_object"}):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "input": f"format {fmt['type']}",
                    "response_format": fmt,
                },
            )
            assert status == 200, (fmt, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_json_schema_format() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "schema format",
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "item_schema",
                        "schema": {"type": "object", "properties": {}},
                    },
                },
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_unknown_response_format_type() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "bad type",
                "response_format": {"type": "xml"},
            },
        )
        assert status == 400, body
        assert "invalid_response_format" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_json_object_with_extra_fields() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "extra",
                "response_format": {"type": "json_object", "strict": True},
            },
        )
        assert status == 400, body
        assert "invalid_response_format" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_json_schema_without_schema_body() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "missing schema",
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "item_schema"},
                },
            },
        )
        assert status == 400, body
        assert "invalid_response_format" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_accepts_text_and_json_object_format()
    test_http_responses_accepts_json_schema_format()
    test_http_responses_rejects_unknown_response_format_type()
    test_http_responses_rejects_json_object_with_extra_fields()
    test_http_responses_rejects_json_schema_without_schema_body()
    print("ok")
