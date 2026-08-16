"""Gateway mode and trace knobs must fail closed on tools passthrough.

``_validate_chat_passthrough_orchestration_controls`` is the live gate.
The leftover ``or``-chain helper is gone: it strip-omitted whitespace
and hid ``mode=conduct`` behind ``orchestration=route``. An invoice
lookup with ``mode=conduct``, whitespace-only alias keys, or
``include_orchestration_trace=true`` must 400 instead of billing a
single-agent ``chat.completion`` with no Conductor workflow and no
TRINITY trusted-trace plane (Nielsen et al., 2025; Xu et al., 2025).

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*.
arXiv. https://arxiv.org/abs/2512.04388

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*Trinity: An evolved LLM coordinator*. arXiv.
https://arxiv.org/abs/2512.04695

OpenAI. (2024). *Create chat completion*. OpenAI API reference.
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
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "passthrough_mode_trace_http_honesty_token"  # noqa: S105

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


def _post(port: int, payload: dict) -> tuple[int, dict | str]:
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
            raw = response.read().decode("utf-8")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def _server():
    server = build_server(
        build(),
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _invoice_tools_body(**extra: object) -> dict:
    payload: dict = {
        "model": "mock-planner",
        "messages": [{"role": "user", "content": "What is the balance on invoice INV-4412?"}],
        "tools": _LOOKUP_TOOLS,
    }
    payload.update(extra)
    return payload


def test_http_chat_tools_rejects_bogus_mode() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(port, _invoice_tools_body(mode="bogus"))
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_conduct_mode() -> None:
    """Conduct is a multi-agent workflow; tools proxy is single-agent only."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _invoice_tools_body(mode="conduct"))
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_mode" in blob
        assert "conduct" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_mixed_route_and_conduct_keys() -> None:
    """A later mode=conduct must not hide behind orchestration=route."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _invoice_tools_body(orchestration="route", mode="conduct"),
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_mode" in blob
        assert "conduct" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_orchestration_conduct() -> None:
    """orchestration=conduct is conduct even when mode is omitted."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _invoice_tools_body(orchestration="conduct"))
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_mode" in blob
        assert "conduct" in blob
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_orchestration_mode_conduct() -> None:
    """orchestration_mode=conduct is conduct even when mode is omitted."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _invoice_tools_body(orchestration_mode="conduct"),
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_mode" in blob
        assert "conduct" in blob
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_whitespace_only_mode() -> None:
    """Whitespace-only mode is truthy on the orchestration or-chain."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _invoice_tools_body(mode="   "))
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_whitespace_only_orchestration_aliases() -> None:
    """Alias keys use the same whitespace-only invalid_mode rule as mode."""
    server, thread, port = _server()
    try:
        for extra in (
            {"orchestration": "   "},
            {"orchestration_mode": "   "},
            {"orchestration": "route", "mode": "   "},
        ):
            status, body = _post(port, _invoice_tools_body(**extra))
            assert status == 400, body
            assert "invalid_mode" in json.dumps(body)
            assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_non_boolean_include_orchestration_trace() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _invoice_tools_body(include_orchestration_trace="yes"),
        )
        assert status == 400, body
        assert "invalid_include_orchestration_trace" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_include_orchestration_trace_true() -> None:
    """Passthrough cannot return a workflow trace — true must not bill silently."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _invoice_tools_body(include_orchestration_trace=True),
        )
        assert status == 400, body
        assert "invalid_include_orchestration_trace" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_stream_rejects_conduct_mode() -> None:
    """SSE tools proxy must 400 before the first chunk when mode=conduct."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _invoice_tools_body(mode="conduct", stream=True))
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_mode" in blob
        assert "conduct" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_stream_rejects_whitespace_only_mode() -> None:
    """SSE tools proxy must 400 JSON, not billed chunks, when mode is spaces."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _invoice_tools_body(mode="   ", stream=True))
        assert status == 400, body
        assert "invalid_mode" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_stream_rejects_include_orchestration_trace_true() -> None:
    """SSE tools proxy must 400 JSON, not billed chunks, when trace=true."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _invoice_tools_body(include_orchestration_trace=True, stream=True),
        )
        assert status == 400, body
        assert "invalid_include_orchestration_trace" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_response_format_rejects_mode_conduct() -> None:
    """response_format plus mode=conduct must not bill a single-agent proxy."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "Summarize invoice INV-4412 as JSON."}
                ],
                "response_format": {"type": "json_object"},
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


def test_http_chat_response_format_rejects_include_orchestration_trace_true() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "Summarize invoice INV-4412 as JSON."}
                ],
                "response_format": {"type": "json_object"},
                "include_orchestration_trace": True,
            },
        )
        assert status == 400, body
        assert "invalid_include_orchestration_trace" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_empty_string_mode_as_omit() -> None:
    """JSON empty-string mode stays omit-equivalent; spaces do not."""
    server, thread, port = _server()
    try:
        status, body = _post(port, _invoice_tools_body(mode=""))
        assert status == 200, body
        assert isinstance(body, dict)
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_route_mode_and_trace_false() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            _invoice_tools_body(mode="route", include_orchestration_trace=False),
        )
        assert status == 200, body
        assert isinstance(body, dict)
        assert body.get("object") == "chat.completion"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_tools_rejects_bogus_mode()
    test_http_chat_tools_rejects_conduct_mode()
    test_http_chat_tools_rejects_mixed_route_and_conduct_keys()
    test_http_chat_tools_rejects_orchestration_conduct()
    test_http_chat_tools_rejects_orchestration_mode_conduct()
    test_http_chat_tools_rejects_whitespace_only_mode()
    test_http_chat_tools_rejects_whitespace_only_orchestration_aliases()
    test_http_chat_tools_rejects_non_boolean_include_orchestration_trace()
    test_http_chat_tools_rejects_include_orchestration_trace_true()
    test_http_chat_tools_stream_rejects_conduct_mode()
    test_http_chat_tools_stream_rejects_whitespace_only_mode()
    test_http_chat_tools_stream_rejects_include_orchestration_trace_true()
    test_http_chat_response_format_rejects_mode_conduct()
    test_http_chat_response_format_rejects_include_orchestration_trace_true()
    test_http_chat_tools_accepts_empty_string_mode_as_omit()
    test_http_chat_tools_accepts_route_mode_and_trace_false()
    print("ok")
