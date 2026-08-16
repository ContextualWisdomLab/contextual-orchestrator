"""Responses ``stream=true`` must SSE-proxy, not return ``400 invalid_stream``.

OpenAI SDKs default ``client.responses.create(..., stream=True)``. Until this
path existed, the gateway returned ``400 invalid_stream`` (honest, but a
buyer-visible gap: every streaming Responses client failed). The transport
must emit ``text/event-stream`` Responses events. Function tools reconstruct
to the same ``output[].type=function_call`` as the non-stream JSON body
(including ``lookup_balance`` / ``INV-9``); content-only streams still match
``output_text``. ``stream_options.include_usage=true`` and non-boolean
``stream`` still fail closed.

OpenAI. (2024). *Streaming API responses*. OpenAI API documentation.
https://platform.openai.com/docs/guides/streaming-responses

OpenAI. (2024). *Create a model response*. OpenAI API reference.
https://platform.openai.com/docs/api-reference/responses/create

WHATWG. (n.d.). *Server-sent events*. HTML Living Standard.
https://html.spec.whatwg.org/multipage/server-sent-events.html
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

_TEST_AUTH_TOKEN = "passthrough_sse_responses_http_honesty_token"  # noqa: S105

_LOOKUP_TOOLS = [
    {
        "type": "function",
        "function": {"name": "lookup_balance", "parameters": {"type": "object"}},
    }
]

_NATIVE_LOOKUP_TOOLS = [
    {"type": "function", "name": "lookup_balance", "parameters": {"type": "object"}}
]


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post_raw(port: int, payload: dict) -> tuple[int, str, str]:
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
            return (
                response.status,
                response.headers.get("content-type", ""),
                response.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", ""), exc.read().decode("utf-8")


def _sse_events(body: str) -> list[dict]:
    events: list[dict] = []
    for block in body.split("\n\n"):
        data_line = ""
        for line in block.splitlines():
            if line.startswith("data: "):
                data_line = line[len("data: ") :]
        if not data_line or data_line == "[DONE]":
            continue
        events.append(json.loads(data_line))
    return events


def _reconstruct_function_call(body: str) -> dict[str, str]:
    """Rebuild a Responses streamed function_call the way the official SDK does."""
    name = ""
    arguments = ""
    call_id = ""
    for event in _sse_events(body):
        event_type = event.get("type")
        if event_type == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                name = str(item.get("name") or "")
                call_id = str(item.get("call_id") or "")
        elif event_type == "response.function_call_arguments.delta":
            arguments += str(event.get("delta") or "")
        elif event_type == "response.function_call_arguments.done":
            arguments = str(event.get("arguments") or arguments)
    return {"name": name, "arguments": arguments, "call_id": call_id}


def _reconstruct_output_text(body: str) -> str:
    pieces: list[str] = []
    for event in _sse_events(body):
        if event.get("type") == "response.output_text.delta":
            pieces.append(str(event.get("delta") or ""))
    return "".join(pieces)


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_proxy_completion_responses_function_tools_bind_invoice() -> None:
    """Realistic invoice lookup on /v1/responses must emit a function_call, not content."""
    result = build().proxy_completion(
        {
            "model": "mock-planner",
            "input": "look up invoice INV-9",
            "tools": _LOOKUP_TOOLS,
        },
        endpoint="responses",
    )
    assert result["object"] == "response"
    item = result["output"][0]
    assert item["type"] == "function_call"
    assert item["name"] == "lookup_balance"
    assert json.loads(item["arguments"]) == {"invoice_id": "INV-9"}


def test_proxy_completion_responses_native_tools_bind_invoice() -> None:
    result = build().proxy_completion(
        {
            "model": "mock-planner",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "invoice INV-42"}]}],
            "tools": _NATIVE_LOOKUP_TOOLS,
            "tool_choice": {"type": "function", "name": "lookup_balance"},
        },
        endpoint="responses",
    )
    item = result["output"][0]
    assert item["type"] == "function_call"
    assert item["name"] == "lookup_balance"
    assert json.loads(item["arguments"]) == {"invoice_id": "INV-42"}


def test_proxy_completion_responses_tool_choice_none_keeps_content() -> None:
    result = build().proxy_completion(
        {
            "model": "mock-planner",
            "input": "look up the invoice",
            "tools": _LOOKUP_TOOLS,
            "tool_choice": "none",
        },
        endpoint="responses",
    )
    item = result["output"][0]
    assert item["type"] == "message"
    assert item["content"][0]["text"] == "[general_agent] responses-mock"


def test_http_responses_stream_emits_function_call_events() -> None:
    """A streamed invoice lookup must not 400; SDK clients reconstruct function_call."""
    server, thread, port = _server()
    try:
        status, content_type, body = _post_raw(
            port,
            {
                "model": "mock-planner",
                "input": "look up invoice INV-9",
                "tools": _LOOKUP_TOOLS,
                "stream": True,
            },
        )
        assert status == 200, body
        assert content_type.startswith("text/event-stream")
        assert "data: [DONE]" in body
        call = _reconstruct_function_call(body)
        assert call["name"] == "lookup_balance"
        assert json.loads(call["arguments"]) == {"invoice_id": "INV-9"}
        types = [event.get("type") for event in _sse_events(body)]
        assert "response.created" in types
        assert "response.completed" in types
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_stream_content_matches_json() -> None:
    server, thread, port = _server()
    try:
        status, content_type, body = _post_raw(
            port,
            {
                "model": "mock-planner",
                "input": "summarize the ledger",
                "stream": True,
            },
        )
        assert status == 200, body
        assert content_type.startswith("text/event-stream")
        assert _reconstruct_output_text(body) == "[general_agent] responses-mock"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_stream_still_rejects_include_usage() -> None:
    server, thread, port = _server()
    try:
        status, _content_type, body = _post_raw(
            port,
            {
                "model": "mock-planner",
                "input": "look up invoice INV-9",
                "tools": _LOOKUP_TOOLS,
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        )
        assert status == 400, body
        blob = body if isinstance(body, str) else json.dumps(body)
        assert "invalid_stream_options" in blob
        assert "include_usage" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_stream_still_rejects_non_boolean_stream() -> None:
    server, thread, port = _server()
    try:
        status, _content_type, body = _post_raw(
            port,
            {
                "model": "mock-planner",
                "input": "hello stream string",
                "stream": "yes",
            },
        )
        assert status == 400, body
        assert "invalid_stream" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_proxy_completion_responses_function_tools_bind_invoice()
    test_proxy_completion_responses_native_tools_bind_invoice()
    test_proxy_completion_responses_tool_choice_none_keeps_content()
    test_http_responses_stream_emits_function_call_events()
    test_http_responses_stream_content_matches_json()
    test_http_responses_stream_still_rejects_include_usage()
    test_http_responses_stream_still_rejects_non_boolean_stream()
    print("ok")
