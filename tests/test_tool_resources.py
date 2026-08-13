"""OpenAI tool_resources validation for file_search and code_interpreter."""

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
    RequestError,
    SecurityConfig,
    _validate_tool_resources,
    build_server,
)

_TEST_AUTH_TOKEN = "tool_res_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_tool_resources() -> None:
    assert _validate_tool_resources({}) is None
    good = {
        "file_search": {"vector_store_ids": ["vs_1"]},
        "code_interpreter": {"file_ids": ["file_1"]},
    }
    assert _validate_tool_resources({"tool_resources": good}) == good
    for bad in (
        "x",
        {"unknown": {}},
        {"file_search": "vs"},
        {"file_search": {"vector_store_ids": [""]}},
        {"code_interpreter": {"file_ids": 1}},
    ):
        try:
            _validate_tool_resources({"tool_resources": bad})
            raise AssertionError(f"expected reject for {bad!r}")
        except RequestError as exc:
            assert exc.code == "invalid_tool_resources"


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


def test_http_chat_accepts_tool_resources() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-generalist",
                "messages": [{"role": "user", "content": "search docs"}],
                "tool_resources": {"file_search": {"vector_store_ids": ["vs_abc"]}},
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_bad_tool_resources() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-generalist",
                "input": "hi",
                "tool_resources": {"file_search": {"vector_store_ids": [""]}},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_tool_resources"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_tool_resources()
    test_http_chat_accepts_tool_resources()
    test_http_responses_rejects_bad_tool_resources()
    print("ok")
