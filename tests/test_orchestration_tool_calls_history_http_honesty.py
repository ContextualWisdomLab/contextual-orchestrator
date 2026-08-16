"""Orchestration path must keep assistant tool_calls history (buyer honesty).

Without a ``tools`` array the chat handler takes the route/conduct path and
rebuilds messages via ``_validate_messages``. Dropping ``tool_calls`` there
makes a follow-up after a tool turn look like an empty assistant reply, so
the buyer cannot recover invoice-style multi-turn tool history.

Citations (APA 7th): OpenAI. (2024a). *Create chat completion*.
https://platform.openai.com/docs/api-reference/chat/create
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    SecurityConfig,
    build_server,
    _validate_messages,
)

_TEST_AUTH_TOKEN = "orchestration_tool_calls_history_http_honesty_token"  # noqa: S105


class RecordingOrchestrator(TaskOrchestrator):
    """Capture the messages the chat handler hands to ``complete``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.seen_messages: list[dict[str, Any]] | None = None

    def complete(self, messages: list[dict[str, Any]], mode: str = "auto") -> dict[str, Any]:
        self.seen_messages = messages
        return super().complete(messages, mode)


def build() -> RecordingOrchestrator:
    return RecordingOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _invoice_tool_history() -> list[dict[str, Any]]:
    """Realistic AR follow-up: lookup an invoice, then ask for the balance."""
    return [
        {"role": "user", "content": "Look up invoice INV-1042 for Acme Corp."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_inv_1042",
                    "type": "function",
                    "function": {
                        "name": "lookup_invoice",
                        "arguments": '{"invoice_id":"INV-1042"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_inv_1042",
            "content": '{"invoice_id":"INV-1042","balance_usd":1280.50,"status":"open"}',
        },
        {"role": "user", "content": "What is the open balance?"},
    ]


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


def _server(orchestrator: RecordingOrchestrator | None = None):
    orch = orchestrator or build()
    server = build_server(orch, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1], orch


def test_validate_messages_keeps_assistant_tool_calls() -> None:
    """Orchestration rebuild must not strip a validated tool-call turn."""
    validated = _validate_messages(_invoice_tool_history())
    assistant = next(message for message in validated if message["role"] == "assistant")
    assert "tool_calls" in assistant
    assert assistant["tool_calls"][0]["id"] == "call_inv_1042"
    assert assistant["tool_calls"][0]["function"]["name"] == "lookup_invoice"
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"invoice_id":"INV-1042"}'
    tool = next(message for message in validated if message["role"] == "tool")
    assert tool["tool_call_id"] == "call_inv_1042"


def test_validate_messages_omits_null_and_empty_tool_calls() -> None:
    validated = _validate_messages(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok", "tool_calls": None},
            {"role": "assistant", "content": "still ok", "tool_calls": []},
        ]
    )
    assert all("tool_calls" not in message for message in validated)


def test_http_orchestration_keeps_invoice_tool_calls_history() -> None:
    """No tools array → orchestration path; complete() must see tool_calls."""
    server, thread, port, orch = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": _invoice_tool_history(),
            },
        )
        assert status == 200, body
        assert orch.seen_messages is not None
        assistant = next(
            message for message in orch.seen_messages if message.get("role") == "assistant"
        )
        assert assistant.get("tool_calls"), assistant
        assert assistant["tool_calls"][0]["id"] == "call_inv_1042"
        assert assistant["tool_calls"][0]["function"]["arguments"] == '{"invoice_id":"INV-1042"}'
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_orchestration_persists_null_arguments_on_history() -> None:
    """SDK arguments:null must stay a JSON-text string on the orchestration path."""
    server, thread, port, orch = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "Look up invoice INV-1042."},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_inv_1042",
                                "type": "function",
                                "function": {"name": "lookup_invoice", "arguments": None},
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call_inv_1042",
                        "content": '{"balance_usd":1280.50}',
                    },
                    {"role": "user", "content": "What is the open balance?"},
                ],
            },
        )
        assert status == 200, body
        assert orch.seen_messages is not None
        assistant = next(
            message for message in orch.seen_messages if message.get("role") == "assistant"
        )
        stored = assistant["tool_calls"][0]["function"]["arguments"]
        assert stored == ""
        assert isinstance(stored, str)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_messages_keeps_assistant_tool_calls()
    test_validate_messages_omits_null_and_empty_tool_calls()
    test_http_orchestration_keeps_invoice_tool_calls_history()
    test_http_orchestration_persists_null_arguments_on_history()
    print("ok")
