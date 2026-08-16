"""Tools/response_format ``stream=true`` must SSE-proxy, not bill a silent JSON body.

OpenAI SDKs and LangChain-style tool callers default to ``stream=true``.
Until this path existed, the gateway returned ``400 invalid_stream`` (honest,
but a buyer-visible gap: every streaming tool client failed). The transport
must now emit ``text/event-stream`` ``chat.completion.chunk`` frames. Function
tools reconstruct to the same ``message.tool_calls`` as the non-stream JSON
body (including ``lookup_balance`` / ``INV-9``); content-only
``response_format`` streams still match ``message.content``. Empty messages,
unsupported knobs, and ``stream_options.include_usage=true`` still fail
closed (this gateway does not emit a final usage chunk).

OpenAI. (2024). *Streaming API responses*. OpenAI API documentation.
https://platform.openai.com/docs/guides/streaming-responses

WHATWG. (n.d.). *Server-sent events*. HTML Living Standard.
https://html.spec.whatwg.org/multipage/server-sent-events.html
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "passthrough_sse_tools_http_honesty_token"  # noqa: S105

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


def _post_raw(port: int, payload: dict) -> tuple[int, str, str]:
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
            return (
                response.status,
                response.headers.get("content-type", ""),
                response.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", ""), exc.read().decode("utf-8")


def _reconstruct_content(sse: str) -> str:
    pieces: list[str] = []
    for block in sse.split("\n\n"):
        line = block.strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        chunk = json.loads(line[len("data: ") :])
        assert chunk["object"] == "chat.completion.chunk"
        delta = chunk["choices"][0].get("delta") or {}
        content = delta.get("content")
        if content:
            pieces.append(content)
    return "".join(pieces)


def _reconstruct_tool_calls(sse: str) -> tuple[list[dict], str | None]:
    """Rebuild OpenAI streamed ``delta.tool_calls`` the way the official SDK does."""
    calls: dict[int, dict] = {}
    finish_reason: str | None = None
    for block in sse.split("\n\n"):
        line = block.strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        chunk = json.loads(line[len("data: ") :])
        assert chunk["object"] == "chat.completion.chunk"
        choice = chunk["choices"][0]
        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]
        for item in (choice.get("delta") or {}).get("tool_calls") or []:
            index = int(item.get("index") or 0)
            slot = calls.setdefault(
                index,
                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
            )
            if item.get("id"):
                slot["id"] = item["id"]
            if item.get("type"):
                slot["type"] = item["type"]
            function = item.get("function") or {}
            if function.get("name"):
                slot["function"]["name"] += function["name"]
            if function.get("arguments"):
                slot["function"]["arguments"] += function["arguments"]
    return [calls[index] for index in sorted(calls)], finish_reason


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_tools_stream_matches_non_stream_tool_calls() -> None:
    """Buyer accuracy: streamed tool-calling deltas equal the JSON completion."""
    server, thread, port = _server()
    payload = {
        "model": "mock-planner",
        "messages": [{"role": "user", "content": "What is the outstanding balance on invoice INV-9?"}],
        "tools": _LOOKUP_TOOLS,
    }
    try:
        json_status, _, json_raw = _post_raw(port, payload)
        sse_status, content_type, sse = _post_raw(port, {**payload, "stream": True})
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert json_status == 200, json_raw
    assert sse_status == 200, sse
    assert content_type.startswith("text/event-stream"), content_type
    assert sse.endswith("data: [DONE]\n\n")
    assert "chat.completion.chunk" in sse
    assert "orchestration" not in sse
    reference = json.loads(json_raw)["choices"][0]
    assert reference["finish_reason"] == "tool_calls"
    assert reference["message"]["content"] is None
    streamed, finish_reason = _reconstruct_tool_calls(sse)
    assert finish_reason == "tool_calls"
    assert streamed == reference["message"]["tool_calls"]
    assert streamed[0]["function"]["name"] == "lookup_balance"
    assert json.loads(streamed[0]["function"]["arguments"]) == {"invoice_id": "INV-9"}
    assert _reconstruct_content(sse) == ""


def test_http_chat_response_format_stream_is_sse() -> None:
    server, thread, port = _server()
    try:
        status, content_type, sse = _post_raw(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "return json"}],
                "response_format": {"type": "json_object"},
                "stream": True,
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 200, sse
    assert content_type.startswith("text/event-stream"), content_type
    assert "chat.completion.chunk" in sse
    assert sse.endswith("data: [DONE]\n\n")


def test_http_chat_tools_stream_still_rejects_empty_messages() -> None:
    server, thread, port = _server()
    try:
        status, _, raw = _post_raw(
            port,
            {
                "model": "mock-planner",
                "messages": [],
                "tools": _LOOKUP_TOOLS,
                "stream": True,
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 400, raw
    assert "invalid_message" in raw


def test_http_chat_tools_stream_still_rejects_seed() -> None:
    server, thread, port = _server()
    try:
        status, _, raw = _post_raw(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "stream": True,
                "seed": 1,
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 400, raw
    assert "invalid_seed" in raw


def test_http_chat_tools_stream_rejects_include_usage() -> None:
    """Usage chunks are not emitted — do not accept include_usage=true."""
    server, thread, port = _server()
    try:
        status, _, raw = _post_raw(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 400, raw
    assert "invalid_stream_options" in raw


def test_proxy_completion_named_tool_choice_binds_invoice_from_content_parts() -> None:
    result = build().proxy_completion(
        {
            "model": "mock-planner",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "call the other tool for INV-42"},
                        {"type": "image_url", "image_url": {"url": "https://example.test/x"}},
                    ],
                }
            ],
            "tools": [
                {"type": "function", "function": {"name": "lookup_balance"}},
                {"type": "function", "function": {"name": "other_tool"}},
            ],
            "tool_choice": {"type": "function", "function": {"name": "other_tool"}},
        }
    )
    call = result["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "other_tool"
    assert json.loads(call["function"]["arguments"]) == {"invoice_id": "INV-42"}


def test_proxy_completion_generic_function_uses_query_argument() -> None:
    result = build().proxy_completion(
        {
            "model": "mock-planner",
            "messages": [{"role": "user", "content": "summarize the ledger"}],
            "tools": [{"type": "function", "function": {"name": "lookup"}}],
        }
    )
    call = result["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "lookup"
    assert json.loads(call["function"]["arguments"]) == {"query": "summarize the ledger"}


def test_proxy_completion_tool_choice_none_keeps_content() -> None:
    result = build().proxy_completion(
        {
            "model": "mock-planner",
            "messages": [{"role": "user", "content": "look up the invoice"}],
            "tools": _LOOKUP_TOOLS,
            "tool_choice": "none",
        }
    )
    assert result["choices"][0]["finish_reason"] == "stop"
    assert "tool_calls" not in result["choices"][0]["message"]
    assert result["choices"][0]["message"]["content"] == "[general_agent] chat-mock"


def test_proxy_completion_defaults_invoice_identifier_when_prompt_omits_it() -> None:
    """Realistic invoice prompt without an id still binds lookup_balance to INV-9."""
    result = build().proxy_completion(
        {
            "model": "mock-planner",
            "messages": [{"role": "user", "content": "look up the invoice"}],
            "tools": _LOOKUP_TOOLS,
        }
    )
    message = result["choices"][0]["message"]
    assert result["choices"][0]["finish_reason"] == "tool_calls"
    assert message["tool_calls"][0]["function"]["name"] == "lookup_balance"
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {
        "invoice_id": "INV-9"
    }


def test_proxy_completion_stream_yields_mock_tool_calls() -> None:
    orch = build()
    frames = list(
        orch.proxy_completion_stream(
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice INV-9"}],
                "tools": _LOOKUP_TOOLS,
                "mode": "auto",
            }
        )
    )
    body = "".join(frames)
    assert "chat.completion.chunk" in body
    assert body.endswith("data: [DONE]\n\n")
    assert '"mode"' not in body
    streamed, finish_reason = _reconstruct_tool_calls(body)
    assert finish_reason == "tool_calls"
    assert streamed[0]["function"]["name"] == "lookup_balance"
    assert json.loads(streamed[0]["function"]["arguments"]) == {"invoice_id": "INV-9"}


def test_stream_raw_pipes_tool_call_deltas_verbatim() -> None:
    """Provider tool_calls deltas must survive — content-only parsers drop them."""
    frames = [
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"lookup_balance","arguments":"{\\"invoice_id\\":\\"INV-9\\"}"}}]}}]}\n\n',
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n',
        "data: [DONE]\n\n",
    ]

    class _FakeSSEProvider:
        def __init__(self, emitted: list[str]) -> None:
            class Handler(BaseHTTPRequestHandler):
                def do_POST(self) -> None:  # noqa: N802
                    length = int(self.headers.get("content-length", 0))
                    self.rfile.read(length)
                    self.send_response(200)
                    self.send_header("content-type", "text/event-stream")
                    self.end_headers()
                    for frame in emitted:
                        self.wfile.write(frame.encode("utf-8"))
                        self.wfile.flush()

                def log_message(self, *args: object) -> None:
                    return

            self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

        def __enter__(self) -> "_FakeSSEProvider":
            self._thread.start()
            return self

        def __exit__(self, *exc: object) -> None:
            self._server.shutdown()

        @property
        def base_url(self) -> str:
            return f"http://127.0.0.1:{self._server.server_address[1]}"

    with _FakeSSEProvider(frames) as provider:
        client = ModelClient()
        agent = ModelAgent(
            "worker_agent",
            "gpt-x",
            base_url=provider.base_url,
            api_key_env="UNSET_KEY_ENV",
        )
        raw = "".join(
            client._stream_raw(
                agent,
                "chat/completions",
                {"model": "gpt-x", "stream": True, "tools": _LOOKUP_TOOLS},
            )
        )
    assert "lookup_balance" in raw
    assert "INV-9" in raw
    assert "tool_calls" in raw
    assert "[DONE]" in raw


if __name__ == "__main__":
    test_http_chat_tools_stream_matches_non_stream_tool_calls()
    test_http_chat_response_format_stream_is_sse()
    test_http_chat_tools_stream_still_rejects_empty_messages()
    test_http_chat_tools_stream_still_rejects_seed()
    test_http_chat_tools_stream_rejects_include_usage()
    test_proxy_completion_named_tool_choice_binds_invoice_from_content_parts()
    test_proxy_completion_generic_function_uses_query_argument()
    test_proxy_completion_tool_choice_none_keeps_content()
    test_proxy_completion_defaults_invoice_identifier_when_prompt_omits_it()
    test_proxy_completion_stream_yields_mock_tool_calls()
    test_stream_raw_pipes_tool_call_deltas_verbatim()
    print("ok")
