"""AP clerks write invoice no / nr / inv# — mock lookup must bind those digits.

Buyer accuracy: a real accounts-payable prompt says ``invoice no. 4419``,
``invoice nr 4419``, or ``inv#4419``. The first-hop ``lookup_balance``
arguments must be ``INV-4419`` on JSON and SSE, not the ``INV-9`` default
used when no identifier is present.

CEN. (2017). *Electronic invoicing — Part 1: Semantic data model of the
core elements of an electronic invoice* (EN 16931-1:2017). European
Committee for Standardization. https://standards.cencenelec.eu/
(BT-1 Invoice number; cite + link only — CEN texts are not OA.)

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

_TEST_AUTH_TOKEN = "invoice_alias_bind_http_honesty_token"  # noqa: S105

_LOOKUP_TOOLS = [
    {
        "type": "function",
        "function": {"name": "lookup_balance", "parameters": {"type": "object"}},
    }
]

_ALIAS_PROMPTS = (
    "What is the outstanding balance on invoice no. 4419?",
    "What is the outstanding balance on invoice no 4419?",
    "What is the outstanding balance on invoice nr 4419?",
    "What is the outstanding balance on invoice is 4419?",
    "What is the outstanding balance on inv#4419?",
    "What is the outstanding balance on inv #4419?",
)


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


def _assert_bound_invoice(raw: str) -> dict:
    body = json.loads(raw)["choices"][0]
    assert body["finish_reason"] == "tool_calls", raw
    arguments = json.loads(body["message"]["tool_calls"][0]["function"]["arguments"])
    assert arguments == {"invoice_id": "INV-4419"}, arguments
    return body["message"]["tool_calls"]


def test_http_chat_tools_binds_invoice_no_nr_inv_hash() -> None:
    """JSON + SSE first hop must bind clerk aliases to the true invoice id."""
    server, thread, port = _server()
    try:
        for prompt in _ALIAS_PROMPTS:
            payload = {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": prompt}],
                "tools": _LOOKUP_TOOLS,
            }
            json_status, _, json_raw = _post_raw(port, payload)
            sse_status, content_type, sse = _post_raw(port, {**payload, "stream": True})
            assert json_status == 200, (prompt, json_raw)
            assert sse_status == 200, (prompt, sse)
            assert content_type.startswith("text/event-stream"), content_type
            reference = _assert_bound_invoice(json_raw)
            streamed, finish_reason = _reconstruct_tool_calls(sse)
            assert finish_reason == "tool_calls", prompt
            assert streamed == reference, prompt
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_tools_binds_invoice_no_nr_inv_hash()
    print("ok")
