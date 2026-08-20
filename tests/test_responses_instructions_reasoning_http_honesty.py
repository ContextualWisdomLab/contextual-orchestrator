"""Responses API instructions and reasoning honesty over HTTP."""

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

_TEST_AUTH_TOKEN = "responses_instructions_reasoning_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
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


def test_http_responses_accepts_nonempty_instructions() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "summarize the ledger",
                "instructions": "Be concise and factual.",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_blank_instructions_as_omit() -> None:
    """Empty/whitespace instructions are SDK omit-equivalent (parity with null)."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "summarize the ledger",
                "instructions": "   ",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_instructions_non_string() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "summarize the ledger",
                "instructions": ["Be concise"],
            },
        )
        assert status == 400, body
        assert "invalid_instructions" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_instructions_too_long() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "summarize the ledger",
                "instructions": "x" * 32_001,
            },
        )
        assert status == 400, body
        assert "invalid_instructions" in json.dumps(body)
        assert "32000" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_reasoning_effort_known_levels() -> None:
    """Known effort levels are default-effort no-ops (no effort plane)."""
    server, thread, port = _server()
    try:
        for effort in ("auto", "low", "medium", "HIGH", "minimal", "none"):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "input": f"think carefully {effort!r}",
                    "reasoning": {"effort": effort},
                },
            )
            assert status == 200, (effort, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_still_rejects_unknown_reasoning_effort() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "think carefully max",
                "reasoning": {"effort": "max"},
            },
        )
        assert status == 400, body
        assert "invalid_reasoning" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_instructions_omitted() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "input": "hello responses",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_responses_accepts_nonempty_instructions()
    test_http_responses_accepts_blank_instructions_as_omit()
    test_http_responses_rejects_instructions_non_string()
    test_http_responses_rejects_instructions_too_long()
    test_http_responses_accepts_reasoning_effort_known_levels()
    test_http_responses_still_rejects_unknown_reasoning_effort()
    test_http_responses_accepts_instructions_omitted()
    print("ok")
