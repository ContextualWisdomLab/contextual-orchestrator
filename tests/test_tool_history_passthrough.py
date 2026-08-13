"""Multi-turn OpenAI tool history must passthrough without 400 on later turns."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    SecurityConfig,
    _messages_require_passthrough,
    _needs_provider_passthrough,
    build_server,
)

_TEST_AUTH_TOKEN = "tool_hist_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing", "coding")),
        ]
    )


def test_messages_require_passthrough_for_tool_turns() -> None:
    assert _messages_require_passthrough(
        [
            {"role": "user", "content": "what is the weather?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 21}'},
        ]
    )
    assert not _messages_require_passthrough(
        [{"role": "user", "content": "plain chat"}]
    )
    assert _needs_provider_passthrough(
        {
            "messages": [
                {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
            ]
        }
    )


def test_http_tool_result_turn_without_tools_array_passes_through() -> None:
    """Buyer path: second turn of a tool loop often omits tools; must not 400."""
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    payload = {
        "model": "mock-generalist",
        "messages": [
            {"role": "user", "content": "what is the weather in Seoul?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_weather_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city":"Seoul"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_weather_1",
                "content": '{"celsius": 18, "condition": "cloudy"}',
            },
        ],
    }
    try:
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
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = json.loads(exc.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    assert body["object"] == "chat.completion"
    # Passthrough mock echoes messages so we know tool history was forwarded.
    echoed = body.get("echo", {}).get("messages") or []
    assert any(m.get("role") == "tool" for m in echoed)
    assert any(m.get("tool_calls") for m in echoed if isinstance(m, dict))


def test_plain_chat_still_orchestrates() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "orchestration": "route",
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert body["object"] == "chat.completion"
    assert "echo" not in body  # orchestrated path, not passthrough


if __name__ == "__main__":
    test_messages_require_passthrough_for_tool_turns()
    test_http_tool_result_turn_without_tools_array_passes_through()
    test_plain_chat_still_orchestrates()
    print("ok")
