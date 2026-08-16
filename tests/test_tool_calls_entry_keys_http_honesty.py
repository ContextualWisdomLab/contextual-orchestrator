"""Assistant tool_calls extra keys must fail closed on tools passthrough.

``_validate_chat_tools`` rejects unknown siblings on ``tools[]`` / ``function``.
Assistant history ``tool_calls`` entries did not: a tool-calling body with
``tool_calls[0].smuggle`` or ``function.extra_hint`` billed a sync completion
and forwarded the raw object to the provider.

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

_LOOKUP_TOOLS = [
    {
        "type": "function",
        "function": {"name": "lookup_balance", "parameters": {"type": "object"}},
    }
]


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict | str]:
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
                return response.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _valid_tool_call() -> dict:
    return {
        "id": "call_1",
        "type": "function",
        "function": {"name": "lookup_balance", "arguments": "{\"q\":\"invoice\"}"},
    }


def test_http_chat_tools_rejects_unknown_tool_call_sibling() -> None:
    """Unknown tool_calls siblings must not smuggle through tools passthrough."""
    server, thread, port = _server()
    try:
        call = _valid_tool_call()
        call["smuggle"] = True
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "invoice lookup"},
                    {"role": "assistant", "content": "", "tool_calls": [call]},
                ],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "unknown_tool_call_fields" in blob
        assert "smuggle" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_unknown_tool_call_function_key() -> None:
    server, thread, port = _server()
    try:
        call = _valid_tool_call()
        call["function"]["extra_hint"] = "drop-me"
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "invoice lookup"},
                    {"role": "assistant", "content": "", "tool_calls": [call]},
                ],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "unknown_tool_call_fields" in blob
        assert "extra_hint" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_known_tool_call_keys() -> None:
    server, thread, port = _server()
    try:
        call = _valid_tool_call()
        call["index"] = 0
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "invoice lookup"},
                    {"role": "assistant", "content": "", "tool_calls": [call]},
                    {
                        "role": "tool",
                        "content": "ok",
                        "tool_call_id": "call_1",
                    },
                ],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 200, body
        assert isinstance(body, dict)
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_tools_rejects_unknown_tool_call_sibling()
    test_http_chat_tools_rejects_unknown_tool_call_function_key()
    test_http_chat_tools_accepts_known_tool_call_keys()
    print("ok")
