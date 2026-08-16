"""Second-hop ``role=tool`` results must become a final answer, not another call.

OpenAI SDKs and LangChain-style clients POST the tool observation after the
first ``tool_calls`` hop and expect ``content`` / ``stop`` (or streamed
content deltas). The mock selector used to look only at ``tools`` /
``tool_choice``, so that second request emitted another ``lookup_balance``.

Buyer accuracy: a real AP clerk looks up invoice 4419, the tool returns
``balance_usd=128.50`` / ``status=open``, and the gateway answer must
reproduce those observed values — not invent a second tool call.

Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y.
(2023). ReAct: Synergizing reasoning and acting in language models.
*International Conference on Learning Representations*.
https://arxiv.org/abs/2210.03629

Schick, T., Dwivedi-Yu, J., Dessì, R., Raileanu, R., Lomeli, M., Hambro, E.,
Zettlemoyer, L., Cancedda, N., & Scialom, T. (2023). Toolformer: Language
models can teach themselves to use tools. *Advances in Neural Information
Processing Systems, 36*. https://arxiv.org/abs/2302.04761

OpenAI. (2024). *Function calling*. OpenAI API documentation.
https://platform.openai.com/docs/guides/function-calling
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

_TEST_AUTH_TOKEN = "tool_result_continuation_http_honesty_token"  # noqa: S105

_LOOKUP_TOOLS = [
    {
        "type": "function",
        "function": {"name": "lookup_balance", "parameters": {"type": "object"}},
    }
]

_INVOICE_OBSERVATION = (
    '{"invoice_id":"INV-4419","balance_usd":"128.50","status":"open"}'
)

_SECOND_HOP_MESSAGES = [
    {
        "role": "user",
        "content": "What is the outstanding balance on invoice 4419?",
    },
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_mock_lookup_balance",
                "type": "function",
                "function": {
                    "name": "lookup_balance",
                    "arguments": '{"invoice_id":"INV-4419"}',
                },
            }
        ],
    },
    {
        "role": "tool",
        "tool_call_id": "call_mock_lookup_balance",
        "content": _INVOICE_OBSERVATION,
    },
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


def _assert_observation_answer(content: str) -> None:
    """True invoice observation must appear in the synthesized answer."""
    assert "INV-4419" in content
    assert "128.50" in content
    assert "open" in content


def test_http_chat_tools_second_hop_synthesizes_observed_balance() -> None:
    """JSON + SSE second hop must stop with the tool's true parameters."""
    server, thread, port = _server()
    payload = {
        "model": "mock-planner",
        "messages": _SECOND_HOP_MESSAGES,
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
    reference = json.loads(json_raw)["choices"][0]
    assert reference["finish_reason"] == "stop"
    assert "tool_calls" not in reference["message"]
    _assert_observation_answer(reference["message"]["content"])
    streamed, finish_reason = _reconstruct_tool_calls(sse)
    assert finish_reason == "stop"
    assert streamed == []
    assert _reconstruct_content(sse) == reference["message"]["content"]


def test_http_chat_tools_unmatched_tool_call_id_still_emits_lookup() -> None:
    """An observation that does not bind a prior tool_call_id is not a result."""
    server, thread, port = _server()
    payload = {
        "model": "mock-planner",
        "messages": [
            {"role": "user", "content": "What is the outstanding balance on invoice 4419?"},
            {
                "role": "tool",
                "tool_call_id": "call_unbound_other",
                "content": _INVOICE_OBSERVATION,
            },
        ],
        "tools": _LOOKUP_TOOLS,
    }
    try:
        status, _, raw = _post_raw(port, payload)
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 200, raw
    body = json.loads(raw)["choices"][0]
    assert body["finish_reason"] == "tool_calls"
    assert body["message"]["tool_calls"][0]["function"]["name"] == "lookup_balance"


def test_http_chat_tools_empty_tool_choice_with_tools_keeps_content() -> None:
    """Empty/whitespace ``tool_choice`` plus tools is omit, not another lookup."""
    server, thread, port = _server()
    try:
        for choice in ("", "   "):
            payload = {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up the invoice"}],
                "tools": _LOOKUP_TOOLS,
                "tool_choice": choice,
            }
            json_status, _, json_raw = _post_raw(port, payload)
            sse_status, content_type, sse = _post_raw(port, {**payload, "stream": True})
            assert json_status == 200, (choice, json_raw)
            assert sse_status == 200, (choice, sse)
            assert content_type.startswith("text/event-stream"), content_type
            reference = json.loads(json_raw)["choices"][0]
            assert reference["finish_reason"] == "stop", choice
            assert "tool_calls" not in reference["message"], choice
            streamed, finish_reason = _reconstruct_tool_calls(sse)
            assert finish_reason == "stop", choice
            assert streamed == []
            assert _reconstruct_content(sse) == reference["message"]["content"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_tools_second_hop_synthesizes_observed_balance()
    test_http_chat_tools_unmatched_tool_call_id_still_emits_lookup()
    test_http_chat_tools_empty_tool_choice_with_tools_keeps_content()
    print("ok")
