"""Completions token-array prompt shapes over HTTP."""

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

_TEST_AUTH_TOKEN = "completions_token_array_prompt_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/completions",
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


def test_http_completions_accepts_token_id_array_prompt() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": [1, 2, 3, 4]},
        )
        assert status == 200, body
        assert "choices" in body, body
        choice = (body.get("choices") or [{}])[0]
        assert choice.get("text") is not None or choice.get("message") is not None, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_batch_of_token_arrays_prompt() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": [[10, 11], [20], [30, 31, 32]]},
        )
        assert status == 200, body
        assert "choices" in body, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_still_rejects_bool_and_negative_token_prompts() -> None:
    server, thread, port = _server()
    try:
        for value in ([True, False], [1, -1], [1, "x"], [[1, 2], "hi"], [[1, -2]]):
            status, body = _post(
                port,
                {"model": "mock-planner", "prompt": value},
            )
            assert status == 400, (value, body)
            assert "invalid_prompt" in json.dumps(body), (value, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_token_prompt_still_accepts_string_array() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": ["alpha", "beta"]},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)
