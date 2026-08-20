"""Chat tools/response_format passthrough must fail-closed on controls.

Before this fix, sampling knobs and unsupported controls were validated only
on the multi-agent route path. tools/response_format early ``proxy_completion``
returned 200 for invalid temperature, seed, store=true, etc.
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
from contextual_orchestrator.server import (  # noqa: E402
    SecurityConfig,
    _validate_chat_max_completion_tokens,
    _validate_completions_temperature,
    _validate_completions_top_p,
    build_server,
)

_TEST_AUTH_TOKEN = "chat_tools_passthrough_controls_http_honesty_token"  # noqa: S105

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_item",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent(
                "general_agent",
                "mock-planner",
                tags=("reasoning", "writing", "tools"),
            )
        ]
    )


def _post(port: int, payload: dict, *, tool_loop: bool = False) -> tuple[int, dict]:
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
        "connection": "close",
    }
    if tool_loop:
        headers["x-contextual-orchestrator-tool-loop"] = "v1"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server():
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _base(**extra: object) -> dict:
    body: dict = {
        "model": "mock-planner",
        "messages": [{"role": "user", "content": "hello tools path"}],
        "tools": _TOOLS,
    }
    body.update(extra)
    return body


def test_unit_sampling_writeback_coerced_numbers() -> None:
    body = {"temperature": "0.5", "top_p": "0.9", "max_completion_tokens": "128"}
    assert _validate_completions_temperature(body) == 0.5
    assert body["temperature"] == 0.5
    assert _validate_completions_top_p(body) == 0.9
    assert body["top_p"] == 0.9
    assert _validate_chat_max_completion_tokens(body) == 128
    assert body["max_completion_tokens"] == 128


def test_http_tools_passthrough_rejects_invalid_temperature() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _base(temperature=3))
        assert status == 400, body
        assert "invalid_temperature" in json.dumps(body)
        status, body = _post(port, _base(temperature="hot"))
        assert status == 400, body
        assert "invalid_temperature" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_passthrough_rejects_unsupported_seed_store_stop_n() -> None:
    server, thread, port = _server()
    try:
        for payload, code in (
            (_base(seed=42), "invalid_seed"),
            (_base(store=True), "invalid_store"),
            (_base(stop="END"), "invalid_stop"),
            (_base(n=2), "invalid_n"),
            (_base(logit_bias={"100": 1.0}), "invalid_logit_bias"),
        ):
            status, body = _post(port, payload)
            assert status == 400, (payload, body)
            assert code in json.dumps(body), (code, body)
        status, body = _post(port, _base(service_tier="flex"))
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_passthrough_rejects_invalid_user_and_stream_options() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _base(user=""))
        assert status == 400, body
        assert "invalid_user" in json.dumps(body)
        status, body = _post(port, _base(user=["not", "a", "string"]))
        assert status == 400, body
        assert "invalid_user" in json.dumps(body)
        status, body = _post(port, _base(stream_options={"include_usage": True}))
        assert status == 400, body
        assert "invalid_stream_options" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_rejects_valid_tool_request_without_explicit_loop_header() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _base(temperature="0.7", top_p="0.95", max_tokens="64"),
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_tools_preserves_valid_tool_request_with_explicit_loop_header() -> None:
    """The opt-in contract preserves provider tool state for OpenCode."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _base(temperature="0.7", top_p="0.95", max_tokens="64"),
            tool_loop=True,
        )
        assert status == 200, body
        assert body["echo"]["temperature"] == 0.7
        assert body["echo"]["max_tokens"] == 64
        assert body["echo"]["tools"] == _TOOLS
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_response_format_passthrough_rejects_seed() -> None:
    """response_format alone also triggers passthrough — same control gate."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "hi"}],
                "response_format": {"type": "json_object"},
                "seed": 7,
            },
        )
        assert status == 400, body
        assert "invalid_seed" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_unit_sampling_writeback_coerced_numbers()
    test_http_tools_passthrough_rejects_invalid_temperature()
    test_http_tools_passthrough_rejects_unsupported_seed_store_stop_n()
    test_http_tools_passthrough_rejects_invalid_user_and_stream_options()
    test_http_tools_passthrough_accepts_coerced_sampling()
    test_http_response_format_passthrough_rejects_seed()
    print("ok")
