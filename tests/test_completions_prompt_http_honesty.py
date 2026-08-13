"""Completions prompt honesty: string/array accepted; token-ids and empties fail-closed."""

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

_TEST_AUTH_TOKEN = "completions_prompt_http_honesty_token"  # noqa: S105


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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_completions_string_prompt_ok() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "draft a one-line payment receipt"},
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_string_array_prompt_ok() -> None:
    """OpenAI multi-string prompt is joined into one completion request."""
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": ["Context: gateway honesty.", "Task: complete the idea."],
            },
        )
        assert status == 200, body
        assert "choices" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_token_id_prompt_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": [1, 2, 3, 4]},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_prompt" in blob
        assert "token" in blob.lower()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_nested_token_id_prompt_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": [[10, 20], [30, 40]]},
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_prompt" in blob
        assert "token" in blob.lower()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_empty_string_prompt_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": "   "},
        )
        assert status == 400, body
        assert "invalid_prompt" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_empty_array_item_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": ["ok", "  "]},
        )
        assert status == 400, body
        assert "invalid_prompt" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_empty_prompt_array_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": []},
        )
        assert status == 400, body
        assert "invalid_prompt" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_missing_prompt_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner"},
        )
        assert status == 400, body
        assert "invalid_prompt" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_non_string_prompt_fail_closed() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {"model": "mock-planner", "prompt": {"text": "nope"}},
        )
        assert status == 400, body
        assert "invalid_prompt" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_completions_string_prompt_ok()
    test_http_completions_string_array_prompt_ok()
    test_http_completions_token_id_prompt_fail_closed()
    test_http_completions_nested_token_id_prompt_fail_closed()
    test_http_completions_empty_string_prompt_fail_closed()
    test_http_completions_empty_array_item_fail_closed()
    test_http_completions_empty_prompt_array_fail_closed()
    test_http_completions_missing_prompt_fail_closed()
    test_http_completions_non_string_prompt_fail_closed()
    print("ok")
