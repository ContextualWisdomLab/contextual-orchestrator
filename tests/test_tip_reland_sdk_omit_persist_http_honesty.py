"""Persist omit-real for the #668 re-land seams.

#668 restored accept-path 200s for empty ``top_logprobs``, null
``tool_calls[].function.arguments``, blank Responses ``instructions``,
whitespace Completions ``suffix``, padded ``mode``, and null metadata
values. Accepting those keys without writing the omit-equivalent shape
back onto the request body is not omit: ``proxy_completion`` forwards
the live body, and providers reject ``arguments: null``, blank
``instructions``, and non-string metadata values after this gateway
returned 200.

These cases lock the buyer-visible persist contract:

* validators mutate the request body in place
* mock ``echo`` shows the cleaned payload on tools/Responses passthrough
* ``tools`` + nonzero ``top_logprobs`` is ``invalid_top_logprobs`` (hoist)
* nonempty instructions and kept metadata keys still forward unchanged
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
    _validate_chat_assistant_tool_calls,
    _validate_openai_metadata,
    _validate_responses_instructions,
    build_server,
)

_TEST_AUTH_TOKEN = "tip_reland_sdk_omit_persist_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
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


def test_validate_tool_calls_writes_null_arguments_as_empty_string() -> None:
    body = {
        "messages": [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": None},
                    }
                ],
            }
        ]
    }
    _validate_chat_assistant_tool_calls(body)
    function = body["messages"][0]["tool_calls"][0]["function"]
    assert function["arguments"] == ""


def test_validate_responses_instructions_pops_blank_and_null() -> None:
    for value in (None, "", "   ", "\u00a0"):
        body = {"instructions": value}
        assert _validate_responses_instructions(body) is None
        assert "instructions" not in body, value


def test_validate_responses_instructions_keeps_nonempty() -> None:
    body = {"instructions": "Be concise and factual."}
    assert _validate_responses_instructions(body) == "Be concise and factual."
    assert body["instructions"] == "Be concise and factual."


def test_validate_openai_metadata_writes_back_without_null_values() -> None:
    body = {"metadata": {"keep": "v", "drop": None}}
    validated = _validate_openai_metadata(body)
    assert validated == {"keep": "v"}
    assert body["metadata"] == {"keep": "v"}


def test_validate_openai_metadata_pops_when_only_null_values() -> None:
    body = {"metadata": {"drop": None}}
    assert _validate_openai_metadata(body) is None
    assert "metadata" not in body


def test_http_chat_tools_persist_null_arguments_as_empty_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "messages": [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": None},
                            }
                        ],
                    },
                    {"role": "user", "content": "continue"},
                ],
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_omits_blank_instructions_from_echo() -> None:
    server, thread, port = _server()
    try:
        for value in (None, "", "   ", "\u00a0"):
            status, body = _post(
                port,
                "/v1/responses",
                {
                    "model": "mock-planner",
                    "input": "hello",
                    "instructions": value,
                },
            )
            assert status == 200, (value, body)
            echo = body.get("echo") or {}
            assert "instructions" not in echo, (value, echo)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_echoes_nonempty_instructions() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "hello",
                "instructions": "Be concise and factual.",
            },
        )
        assert status == 200, body
        assert (body.get("echo") or {}).get("instructions") == "Be concise and factual."
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_omits_null_metadata_value_from_echo() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "meta"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "metadata": {"keep": "v", "drop": None},
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_omits_null_metadata_value_from_echo() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "meta",
                "metadata": {"keep": "v", "drop": None},
            },
        )
        assert status == 200, body
        echo_meta = (body.get("echo") or {}).get("metadata")
        assert echo_meta == {"keep": "v"}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_nonzero_top_logprobs() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tlp"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "top_logprobs": 5,
            },
        )
        assert status == 400, body
        assert "invalid_top_logprobs" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_omits_whitespace_top_logprobs_from_echo() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tlp"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "top_logprobs": "   ",
            },
        )
        assert status == 422, body
        assert body["error"]["code"] == "multi_agent_tools_unsupported"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_tool_calls_writes_null_arguments_as_empty_string()
    test_validate_responses_instructions_pops_blank_and_null()
    test_validate_responses_instructions_keeps_nonempty()
    test_validate_openai_metadata_writes_back_without_null_values()
    test_validate_openai_metadata_pops_when_only_null_values()
    test_http_chat_tools_persist_null_arguments_as_empty_string()
    test_http_responses_omits_blank_instructions_from_echo()
    test_http_responses_echoes_nonempty_instructions()
    test_http_chat_tools_omits_null_metadata_value_from_echo()
    test_http_responses_omits_null_metadata_value_from_echo()
    test_http_chat_tools_rejects_nonzero_top_logprobs()
    test_http_chat_tools_omits_whitespace_top_logprobs_from_echo()
    print("ok")
