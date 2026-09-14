"""tool_choice none/auto without tools as omit no-ops over HTTP."""

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

_TEST_AUTH_TOKEN = "tool_choice_auto_without_tools_noop_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing", "embedding"))]
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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_chat_accepts_tool_choice_auto_without_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "auto no tools"}],
                "tool_choice": "auto",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_choice_none_without_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "none no tools"}],
                "tool_choice": "none",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_tool_choice_auto_with_empty_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "auto empty tools"}],
                "tools": [],
                "tool_choice": "auto",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_tool_choice_auto_without_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "auto no tools",
                "tool_choice": "auto",
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_noop_tool_controls_are_omitted_from_provider_request() -> None:
    """Omit no-op tool controls instead of forwarding an invalid provider payload."""
    orchestrator = build()
    observed_settings: list[dict[str, object]] = []
    original_chat = orchestrator.client.chat

    def observed_chat(agent, messages, **kwargs):
        observed_settings.append(orchestrator.client.request_settings_snapshot())
        return original_chat(agent, messages, **kwargs)

    orchestrator.client.chat = observed_chat  # type: ignore[method-assign]
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for tool_choice in ("auto", "none"):
            status, body = _post(
                server.server_address[1],
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "no tools"}],
                    "tool_choice": tool_choice,
                    "parallel_tool_calls": False,
                },
            )
            assert status == 200, body
        assert observed_settings
        assert all("tools" not in settings for settings in observed_settings)
        assert all("tool_choice" not in settings for settings in observed_settings)
        assert all("parallel_tool_calls" not in settings for settings in observed_settings)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_tool_choice_required_without_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "required no tools"}],
                "tool_choice": "required",
            },
        )
        assert status == 400, body
        assert "invalid_tool_choice" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)
