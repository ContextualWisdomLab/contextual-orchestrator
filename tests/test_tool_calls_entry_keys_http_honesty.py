"""Chat assistant tool_calls entry/function key honesty over HTTP.

OpenAI assistant ``tool_calls`` objects accept ``id``, ``type``, ``function``,
and optional ``index`` (stream-assembled histories). Extra keys on the entry
or on ``function`` must fail closed with named errors so a billed completion
never smuggles unknown fields to the provider. The same gate runs on the
tools / ``response_format`` passthrough path, including ``stream=true``.

OpenAI. (2024). *Create chat completion*. OpenAI API reference.
https://platform.openai.com/docs/api-reference/chat/create
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

_TEST_AUTH_TOKEN = "tool_calls_entry_keys_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, {
                    "_raw": raw,
                    "_content_type": response.headers.get("content-type", ""),
                }
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


def _valid_call(**extra: object) -> dict:
    call: dict = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "lookup_item", "arguments": '{"q":"invoice-4412"}'},
    }
    call.update(extra)
    return call


def _history_payload(tool_call: dict, **extra: object) -> dict:
    payload = {
        "model": "mock-planner",
        "messages": [
            {"role": "user", "content": "What is the balance on invoice 4412?"},
            {"role": "assistant", "content": "", "tool_calls": [tool_call]},
            {"role": "tool", "content": "4412 paid", "tool_call_id": "call_1"},
            {"role": "user", "content": "thanks"},
        ],
    }
    payload.update(extra)
    return payload


def _lookup_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {"name": "lookup_item", "parameters": {"type": "object"}},
        }
    ]


def test_http_chat_accepts_tool_calls_with_optional_index() -> None:
    server, thread, port = _server()
    try:
        for index in (0, 1):
            status, body = _post(port, _history_payload(_valid_call(index=index)))
            assert status == 200, (index, body)
        status, body = _post(port, _history_payload(_valid_call(index=None)))
        assert status == 200, body
        status, body = _post(port, _history_payload(_valid_call()))
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_tool_call_entry_fields() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _history_payload(_valid_call(extra=True)))
        assert status == 400, body
        blob = json.dumps(body)
        assert "unknown_tool_call_fields" in blob
        assert "extra" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_tool_call_function_fields() -> None:
    server, thread, port = _server()
    try:
        call = _valid_call()
        call["function"] = {
            "name": "lookup_item",
            "arguments": "{}",
            "description": "smuggle",
        }
        status, body = _post(port, _history_payload(call))
        assert status == 400, body
        blob = json.dumps(body)
        assert "unknown_tool_call_function_fields" in blob
        assert "description" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_invalid_tool_call_index() -> None:
    server, thread, port = _server()
    try:
        for index in (-1, True, 1.5, "0"):
            status, body = _post(port, _history_payload(_valid_call(index=index)))
            assert status == 400, (index, body)
            assert "invalid_tool_calls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_tool_call_fields_with_tools() -> None:
    """Unknown tool_calls keys must fail closed on the tools passthrough path."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _history_payload(_valid_call(extra=True), tools=_lookup_tools()),
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "unknown_tool_call_fields" in blob
        assert "extra" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_tool_call_fields_with_tools_stream() -> None:
    """SSE tools proxy must reject unknown keys before the first byte."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _history_payload(
                _valid_call(extra=True),
                tools=_lookup_tools(),
                stream=True,
            ),
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "unknown_tool_call_fields" in blob
        assert "extra" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_tool_calls_with_optional_index()
    test_http_chat_rejects_unknown_tool_call_entry_fields()
    test_http_chat_rejects_unknown_tool_call_function_fields()
    test_http_chat_rejects_invalid_tool_call_index()
    test_http_chat_rejects_unknown_tool_call_fields_with_tools()
    test_http_chat_rejects_unknown_tool_call_fields_with_tools_stream()
    print("ok")
