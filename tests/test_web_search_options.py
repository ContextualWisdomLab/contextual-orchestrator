"""OpenAI web_search_options validation on chat and Responses."""

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
    _validate_web_search_options,
    build_server,
)

_TEST_AUTH_TOKEN = "web_search_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_web_search_options() -> None:
    assert _validate_web_search_options({}) is None
    good = {"search_context_size": "medium", "user_location": {"type": "approximate"}}
    assert _validate_web_search_options({"web_search_options": good}) == good
    for bad in (
        "x",
        {"search_context_size": "huge"},
        {"user_location": "seoul"},
        {"user_location": {"type": "exact"}},
        {"foo": 1},
    ):
        try:
            _validate_web_search_options({"web_search_options": bad})
            raise AssertionError(f"expected reject for {bad!r}")
        except RequestError as exc:
            assert exc.code == "invalid_web_search_options"


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


def test_http_chat_accepts_web_search_options() -> None:
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
                "messages": [{"role": "user", "content": "news?"}],
                "web_search_options": {"search_context_size": "low"},
            },
        )
        assert status in {200, 202}, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_bad_context_size() -> None:
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
                "input": "news?",
                "web_search_options": {"search_context_size": "huge"},
            },
        )
        assert status == 400, body
        assert body["error"]["code"] == "invalid_web_search_options"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_web_search_options()
    test_http_chat_accepts_web_search_options()
    test_http_responses_rejects_bad_context_size()
    print("ok")
