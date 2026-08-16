"""Tools passthrough must fail closed on route-path request knobs.

``seed``, ``stop``, ``n>1``, ``logprobs``, ``logit_bias``, out-of-range
penalties, and ``reasoning_effort`` already 400 on the orchestration path.
On #597 they still sit after the tools / ``response_format`` early-return, so
an SDK tool-calling body can bill a ``chat.completion`` while those knobs
are silently dropped. Buyers who send ``seed`` for a reproducible invoice
lookup must get ``invalid_seed``, not a billed answer that ignored the seed.

OpenAI. (2024). *Create chat completion*. OpenAI API reference.
https://platform.openai.com/docs/api-reference/chat/create
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

_TEST_AUTH_TOKEN = "passthrough_request_knobs_http_honesty_token"  # noqa: S105

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


def test_http_chat_tools_rejects_seed() -> None:
    """A billed tool call that ignored seed is not a reproducible lookup."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "seed": 1,
            },
        )
        assert status == 400, body
        assert "invalid_seed" in json.dumps(body)
        assert "choices" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_stop_sequences() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "stop": ["END"],
            },
        )
        assert status == 400, body
        assert "invalid_stop" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_n_greater_than_one() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "n": 2,
            },
        )
        assert status == 400, body
        assert "invalid_n" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_logprobs_true() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "logprobs": True,
            },
        )
        assert status == 400, body
        assert "invalid_logprobs" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_logit_bias() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "logit_bias": {"1": 1},
            },
        )
        assert status == 400, body
        assert "invalid_logit_bias" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_presence_penalty_out_of_range() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "presence_penalty": 3,
            },
        )
        assert status == 400, body
        assert "invalid_presence_penalty" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_frequency_penalty_out_of_range() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "frequency_penalty": 3,
            },
        )
        assert status == 400, body
        assert "invalid_frequency_penalty" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_unknown_reasoning_effort() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "reasoning_effort": "invalid_level",
            },
        )
        assert status == 400, body
        assert "invalid_reasoning_effort" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_unknown_service_tier() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "service_tier": "not-a-tier",
            },
        )
        assert status == 400, body
        assert "invalid_service_tier" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_top_logprobs() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "top_logprobs": 5,
            },
        )
        assert status == 400, body
        assert "invalid_top_logprobs" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_boolean_top_logprobs() -> None:
    """JSON false is not integer 0; do not treat it as omit and bill."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "top_logprobs": False,
            },
        )
        assert status == 400, body
        assert "invalid_top_logprobs" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_rejects_zero_max_tokens_when_preferred_budget_is_omit() -> None:
    """SDK null max_completion_tokens must not hide a zero legacy budget."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "max_completion_tokens": None,
                "max_tokens": 0,
            },
        )
        assert status == 400, body
        assert "invalid_max_tokens" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_positive_max_tokens_when_preferred_budget_is_omit() -> None:
    """Null preferred budget falls back to a valid legacy max_tokens."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "max_completion_tokens": None,
                "max_tokens": 16,
            },
        )
        assert status == 200, body
        assert isinstance(body, dict) and "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_response_format_rejects_seed() -> None:
    """JSON-mode bodies must not bill when seed is silently dropped."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "return the invoice as json"}],
                "response_format": {"type": "json_object"},
                "seed": 1,
            },
        )
        assert status == 400, body
        assert "invalid_seed" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_tools_accepts_omit_equivalent_seed_null() -> None:
    """SDK optional ``seed: null`` stays an honest no-op on passthrough."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "look up invoice 4419"}],
                "tools": _LOOKUP_TOOLS,
                "seed": None,
            },
        )
        assert status == 200, body
        assert isinstance(body, dict) and "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_tools_rejects_seed()
    test_http_chat_tools_rejects_stop_sequences()
    test_http_chat_tools_rejects_n_greater_than_one()
    test_http_chat_tools_rejects_logprobs_true()
    test_http_chat_tools_rejects_logit_bias()
    test_http_chat_tools_rejects_presence_penalty_out_of_range()
    test_http_chat_tools_rejects_frequency_penalty_out_of_range()
    test_http_chat_tools_rejects_unknown_reasoning_effort()
    test_http_chat_tools_rejects_unknown_service_tier()
    test_http_chat_tools_rejects_top_logprobs()
    test_http_chat_tools_rejects_boolean_top_logprobs()
    test_http_chat_tools_rejects_zero_max_tokens_when_preferred_budget_is_omit()
    test_http_chat_tools_accepts_positive_max_tokens_when_preferred_budget_is_omit()
    test_http_chat_response_format_rejects_seed()
    test_http_chat_tools_accepts_omit_equivalent_seed_null()
    print("ok")
