"""reasoning_effort low/medium/high accepted as default-effort no-ops over HTTP."""

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

_TEST_AUTH_TOKEN = "reasoning_effort_low_medium_high_noop_http_honesty_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=10) as response:
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


def test_http_chat_accepts_reasoning_effort_levels_casefold() -> None:
    server, thread, port = _server()
    try:
        for val in ("low", "MEDIUM", " High ", "high", "minimal", "none"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"effort {val!r}"}],
                    "reasoning_effort": val,
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_reasoning_effort_levels() -> None:
    server, thread, port = _server()
    try:
        for val in ("low", "medium", "high"):
            status, body = _post(
                port,
                "/v1/completions",
                {
                    "model": "mock-planner",
                    "prompt": f"effort {val!r}",
                    "reasoning_effort": val,
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_reasoning_effort_levels() -> None:
    server, thread, port = _server()
    try:
        for val in ("low", "medium", "HIGH"):
            status, body = _post(
                port,
                "/v1/responses",
                {
                    "model": "mock-planner",
                    "input": f"reason {val!r}",
                    "reasoning": {"effort": val},
                },
            )
            assert status == 200, (val, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_unknown_reasoning_effort() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "effort max"}],
                "reasoning_effort": "max",
            },
        )
        assert status == 400, body
        assert "invalid_reasoning_effort" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_still_rejects_unknown_reasoning_effort() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "reason max",
                "reasoning": {"effort": "max"},
            },
        )
        assert status == 400, body
        assert "invalid_reasoning" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_reasoning_effort_levels_casefold()
    test_http_completions_accepts_reasoning_effort_levels()
    test_http_responses_accepts_reasoning_effort_levels()
    test_http_chat_still_rejects_unknown_reasoning_effort()
    test_http_responses_still_rejects_unknown_reasoning_effort()
    print("ok")
