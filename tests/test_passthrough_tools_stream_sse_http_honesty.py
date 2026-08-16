"""Tools/response_format passthrough must stream OpenAI SSE, not reject or bill JSON.

OpenAI SDKs default tool-calling bodies to ``stream=true``. This gateway used to
return 400 ``invalid_stream`` (or worse, a JSON ``chat.completion`` while the
SDK waited for SSE). Buyers need live ``chat.completion.chunk`` frames that
carry ``tool_calls`` deltas so the default SDK path works.

Citations (APA 7th):
    Hickson, I. (Ed.). (2015). *Server-Sent Events*. World Wide Web Consortium.
        https://www.w3.org/TR/eventsource/
    OpenAI. (n.d.). *Chat Completions API*.
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
from contextual_orchestrator.orchestrator import (  # noqa: E402
    _first_tool_function_name,
    _sse_completion_frame,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "passthrough_tools_stream_sse_http_honesty_token"  # noqa: S105

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


def _post(port: int, payload: dict) -> tuple[int, str]:
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
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_streams_sse_tool_calls_with_tools() -> None:
    """Default SDK tool-calling stream must return tool_calls chunks, not 400 or JSON."""
    server, thread, port = _server()
    try:
        status, raw = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice balance"}],
                "tools": _LOOKUP_TOOLS,
                "stream": True,
            },
        )
        assert status == 200, raw
        assert "chat.completion.chunk" in raw
        assert "tool_calls" in raw
        assert "lookup_balance" in raw
        assert "data: [DONE]" in raw
        assert '"object": "chat.completion"' not in raw.replace("chat.completion.chunk", "")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_streams_sse_with_response_format() -> None:
    server, thread, port = _server()
    try:
        status, raw = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "return json"}],
                "response_format": {"type": "json_object"},
                "stream": True,
            },
        )
        assert status == 200, raw
        assert "chat.completion.chunk" in raw
        assert "data: [DONE]" in raw
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_without_stream_still_json() -> None:
    """Non-stream tool calls stay a single chat.completion JSON body."""
    server, thread, port = _server()
    try:
        status, raw = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice balance"}],
                "tools": _LOOKUP_TOOLS,
            },
        )
        assert status == 200, raw
        body = json.loads(raw)
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_proxy_completion_stream_yields_tool_calls() -> None:
    """Invoice-lookup tools body must stream the named function, not JSON."""
    frames = list(
        build().proxy_completion_stream(
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice balance"}],
                "tools": _LOOKUP_TOOLS,
                "mode": "auto",
            }
        )
    )
    blob = "".join(frames)
    assert "chat.completion.chunk" in blob
    assert "lookup_balance" in blob
    assert "data: [DONE]" in blob


def test_first_tool_function_name_skips_non_function_entries() -> None:
    assert _first_tool_function_name({}) is None
    assert _first_tool_function_name({"tools": "nope"}) is None
    assert _first_tool_function_name({"tools": [None, {"type": "function"}]}) is None
    assert (
        _first_tool_function_name(
            {"tools": [{"function": {"name": "  lookup_balance  "}}]}
        )
        == "lookup_balance"
    )


def test_sse_completion_frame_is_event_source() -> None:
    frame = _sse_completion_frame("chatcmpl_x", 1, "mock-planner", {"content": "hi"})
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    assert "chat.completion.chunk" in frame


def test_http_chat_rejects_include_usage_on_tools_stream() -> None:
    """Usage-on-stream is still unsupported; fail closed instead of a silent drop."""
    server, thread, port = _server()
    try:
        status, raw = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice balance"}],
                "tools": _LOOKUP_TOOLS,
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        )
        assert status == 400, raw
        assert "invalid_stream_options" in raw
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_streams_sse_tool_calls_with_tools()
    test_http_chat_streams_sse_with_response_format()
    test_http_chat_tools_without_stream_still_json()
    test_http_chat_rejects_include_usage_on_tools_stream()
    test_proxy_completion_stream_yields_tool_calls()
    test_first_tool_function_name_skips_non_function_entries()
    test_sse_completion_frame_is_event_source()
    print("ok")
