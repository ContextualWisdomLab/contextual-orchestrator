"""Chat assistant tool_calls entry/function key honesty over HTTP."""

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


def _payload(tool_call: dict) -> dict:
    return {
        "model": "mock-planner",
        "messages": [
            {"role": "user", "content": "use the tool"},
            {"role": "assistant", "content": "", "tool_calls": [tool_call]},
            {"role": "tool", "content": "ok", "tool_call_id": "call_1"},
            {"role": "user", "content": "thanks"},
        ],
    }


def _valid_call(**extra) -> dict:
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "lookup_item", "arguments": "{\"q\":\"x\"}"},
    }
    call.update(extra)
    return call


def test_http_chat_accepts_tool_calls_with_optional_index() -> None:
    server, thread, port = _server()
    try:
        for index in (None, 0, 1):
            call = _valid_call()
            if index is not None or index is None:
                call["index"] = index
            status, body = _post(port, _payload(call))
            assert status == 200, (index, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_tool_call_entry_fields() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _payload(_valid_call(extra=True)))
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
        status, body = _post(port, _payload(call))
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
            status, body = _post(port, _payload(_valid_call(index=index)))
            assert status == 400, (index, body)
            assert "invalid_tool_calls" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_tool_call_fields_with_tools() -> None:
    """Unknown tool_calls keys must fail closed on the tools passthrough path."""
    server, thread, port = _server()
    try:
        payload = _payload(_valid_call(extra=True))
        payload["tools"] = [
            {
                "type": "function",
                "function": {"name": "lookup_item", "parameters": {"type": "object"}},
            }
        ]
        status, body = _post(port, payload)
        assert status == 400, body
        blob = json.dumps(body)
        assert "unknown_tool_call_fields" in blob
        assert "extra" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_rejects_unknown_tool_call_function_fields_with_tools() -> None:
    """Unknown tool_calls.function keys must fail closed on the tools path."""
    server, thread, port = _server()
    try:
        call = _valid_call()
        call["function"] = {
            "name": "lookup_item",
            "arguments": "{}",
            "description": "smuggle",
        }
        payload = _payload(call)
        payload["tools"] = [
            {
                "type": "function",
                "function": {"name": "lookup_item", "parameters": {"type": "object"}},
            }
        ]
        status, body = _post(port, payload)
        assert status == 400, body
        blob = json.dumps(body)
        assert "unknown_tool_call_function_fields" in blob
        assert "description" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_tool_calls_with_optional_index()
    test_http_chat_rejects_unknown_tool_call_entry_fields()
    test_http_chat_rejects_unknown_tool_call_function_fields()
    test_http_chat_rejects_invalid_tool_call_index()
    test_http_chat_rejects_unknown_tool_call_fields_with_tools()
    test_http_chat_rejects_unknown_tool_call_function_fields_with_tools()
    print("ok")
