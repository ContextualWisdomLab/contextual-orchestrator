"""Tools passthrough must fail closed on mode and orchestration-trace knobs.

``mode`` / ``orchestration`` / ``orchestration_mode`` and
``include_orchestration_trace`` already 400 on the orchestration path when
the value is invalid. On #601 they still sit after the tools /
``response_format`` early-return, so an SDK tool-calling body can bill a
``chat.completion`` while ``mode=explode`` is ignored and
``include_orchestration_trace="yes"`` is stripped. A buyer who asked for
Conductor-style deep orchestration (``mode=conduct``) or a trusted trace
must not receive a billed proxy with neither a workflow nor a trace.

OpenAI. (2024). *Create chat completion*. OpenAI API reference.
https://platform.openai.com/docs/api-reference/chat/create

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*.
arXiv. https://doi.org/10.48550/arXiv.2512.04388

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*Trinity: An evolved LLM coordinator*. arXiv.
https://doi.org/10.48550/arXiv.2512.04695
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "passthrough_mode_trace_http_honesty_token"  # noqa: S105

_LOOKUP_TOOLS = [
    {
        "type": "function",
        "function": {"name": "lookup_balance", "parameters": {"type": "object"}},
    }
]


def build() -> TaskOrchestrator:
    """Return a single-agent pool used by the live HTTP cases."""
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    """POST ``/v1/chat/completions`` and return status plus JSON body."""
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


def _server():
    """Start a loopback server with the honesty-stack auth token."""
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_tools_rejects_invalid_mode() -> None:
    """A billed tool call that ignored mode=explode is not an honest reject."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "mode": "explode",
            },
        )
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_whitespace_only_mode() -> None:
    """Whitespace-only mode is truthy on the orchestration ``or`` chain."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "mode": "   ",
            },
        )
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_invalid_orchestration_alias() -> None:
    """``orchestration=explode`` must use the same named error as ``mode``."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "orchestration": "explode",
            },
        )
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_invalid_orchestration_mode_alias() -> None:
    """``orchestration_mode=explode`` must use the same named error as ``mode``."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "orchestration_mode": "explode",
            },
        )
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_non_boolean_include_orchestration_trace() -> None:
    """``include_orchestration_trace="yes"`` must not bill a stripped completion."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "include_orchestration_trace": "yes",
            },
        )
        assert status == 400, body
        assert "invalid_include_orchestration_trace" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_include_orchestration_trace_true() -> None:
    """Passthrough has no Conductor trace plane; true must not silently strip."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "include_orchestration_trace": True,
            },
        )
        assert status == 400, body
        assert "invalid_include_orchestration_trace" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_mode_conduct() -> None:
    """``mode=conduct`` plus tools must not bill a single-worker proxy."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "mode": "conduct",
            },
        )
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_mixed_route_and_conduct_keys() -> None:
    """``orchestration=route`` must not hide ``mode=conduct`` on passthrough.

    An ``or`` chain that prefers the first truthy alias bills a single-agent
    proxy while the buyer still asked for a Conductor workflow.
    """
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "orchestration": "route",
                "mode": "conduct",
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_mode" in blob
        assert "conduct" in blob
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_mixed_route_and_whitespace_mode() -> None:
    """``orchestration=route`` must not hide whitespace-only ``mode``."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "orchestration": "route",
                "mode": "   ",
            },
        )
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_response_format_rejects_invalid_mode() -> None:
    """``response_format`` uses the same early-return as ``tools``."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "response_format": {"type": "json_object"},
                "mode": "explode",
            },
        )
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_response_format_rejects_mode_conduct() -> None:
    """``response_format`` plus ``mode=conduct`` must not bill a proxy."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "response_format": {"type": "json_object"},
                "mode": "conduct",
            },
        )
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_mode_auto_and_false_trace() -> None:
    """Honest no-ops: ``mode=auto`` and ``include_orchestration_trace=false``."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "mode": "auto",
                "include_orchestration_trace": False,
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_empty_string_mode_as_omit() -> None:
    """JSON empty-string mode stays omit-equivalent; spaces do not."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "mode": "",
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_mode_route() -> None:
    """``mode=route`` is an advertised omit-equivalent no-op on passthrough."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "mode": "route",
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_null_trace_as_omit() -> None:
    """SDK-default ``include_orchestration_trace=null`` stays an omit no-op."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "include_orchestration_trace": None,
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_tools_rejects_invalid_mode()
    test_http_chat_tools_rejects_whitespace_only_mode()
    test_http_chat_tools_rejects_invalid_orchestration_alias()
    test_http_chat_tools_rejects_invalid_orchestration_mode_alias()
    test_http_chat_tools_rejects_non_boolean_include_orchestration_trace()
    test_http_chat_tools_rejects_include_orchestration_trace_true()
    test_http_chat_tools_rejects_mode_conduct()
    test_http_chat_tools_rejects_mixed_route_and_conduct_keys()
    test_http_chat_tools_rejects_mixed_route_and_whitespace_mode()
    test_http_chat_response_format_rejects_invalid_mode()
    test_http_chat_response_format_rejects_mode_conduct()
    test_http_chat_tools_accepts_mode_auto_and_false_trace()
    test_http_chat_tools_accepts_empty_string_mode_as_omit()
    test_http_chat_tools_accepts_mode_route()
    test_http_chat_tools_accepts_null_trace_as_omit()
    print("ok")
