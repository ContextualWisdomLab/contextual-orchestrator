"""Casefold honesty for reasoning_effort none, response_format/text.format types, modalities text."""

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

_TEST_AUTH_TOKEN = "reasoning_format_modalities_casefold_http_honesty_token"  # noqa: S105


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


def test_http_chat_accepts_reasoning_effort_none_padded_casefold() -> None:
    server, thread, port = _server()
    try:
        for value in ("none", "NONE", " None ", "None"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "effort"}],
                    "reasoning_effort": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_reasoning_effort_none_padded_casefold() -> None:
    server, thread, port = _server()
    try:
        for value in ("none", "NONE", " None "):
            status, body = _post(
                port,
                "/v1/completions",
                {
                    "model": "mock-planner",
                    "prompt": "effort",
                    "reasoning_effort": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_non_none_reasoning_effort() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "effort high"}],
                "reasoning_effort": "HIGH",
            },
        )
        assert status == 400, body
        assert "invalid_reasoning_effort" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_response_format_type_padded_casefold() -> None:
    server, thread, port = _server()
    try:
        for value in ("text", "TEXT", " Text ", "json_object", "JSON_OBJECT", " Json_Object "):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "rf"}],
                    "response_format": {"type": value},
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_response_format_json_schema_type_casefold() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "rf schema"}],
                "response_format": {
                    "type": " JSON_SCHEMA ",
                    "json_schema": {
                        "name": "answer_box",
                        "schema": {"type": "object"},
                    },
                },
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_text_format_type_padded_casefold() -> None:
    server, thread, port = _server()
    try:
        for value in ("text", "TEXT", " Text ", "json_object", "JSON_OBJECT"):
            status, body = _post(
                port,
                "/v1/responses",
                {
                    "model": "mock-planner",
                    "input": "text format",
                    "text": {"format": {"type": value}},
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_modalities_text_padded_casefold() -> None:
    server, thread, port = _server()
    try:
        for value in (["text"], ["TEXT"], [" Text "], ["Text"]):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "mods"}],
                    "modalities": value,
                },
            )
            assert status == 200, (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_modalities_text_padded_casefold() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "mods",
                "modalities": [" TEXT "],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_modalities_text_padded_casefold() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "mods",
                "modalities": ["TEXT"],
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_non_text_modalities() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "audio"}],
                "modalities": ["AUDIO"],
            },
        )
        assert status == 400, body
        assert "invalid_modalities" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_reasoning_effort_none_padded_casefold()
    test_http_completions_accepts_reasoning_effort_none_padded_casefold()
    test_http_chat_still_rejects_non_none_reasoning_effort()
    test_http_chat_accepts_response_format_type_padded_casefold()
    test_http_chat_accepts_response_format_json_schema_type_casefold()
    test_http_responses_accepts_text_format_type_padded_casefold()
    test_http_chat_accepts_modalities_text_padded_casefold()
    test_http_responses_accepts_modalities_text_padded_casefold()
    test_http_completions_accepts_modalities_text_padded_casefold()
    test_http_chat_still_rejects_non_text_modalities()
    print("ok")
