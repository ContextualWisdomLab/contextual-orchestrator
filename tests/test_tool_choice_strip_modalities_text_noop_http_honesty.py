"""Whitespace-padded tool_choice/function_call none/auto and Completions modalities text no-ops."""

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

_TEST_AUTH_TOKEN = "tool_choice_strip_modalities_text_noop_http_token"  # noqa: S105


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
        with urllib.request.urlopen(request, timeout=15) as response:
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


def test_http_chat_accepts_padded_tool_choice_none_auto() -> None:
    server, thread, port = _server()
    try:
        for tc in (" none ", "\tauto\n", " none"):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"tc {tc!r}"}],
                    "tool_choice": tc,
                },
            )
            assert status == 200, (tc, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_padded_function_call_none_auto() -> None:
    server, thread, port = _server()
    try:
        for fc in (" none ", " auto "):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"fc {fc!r}"}],
                    "function_call": fc,
                },
            )
            assert status == 200, (fc, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_padded_tool_choice_function_call() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": "tc pad", "tool_choice": " none "},
        )
        assert status == 200, body
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": "fc pad", "function_call": " auto "},
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_accepts_modalities_text_as_noop() -> None:
    server, thread, port = _server()
    try:
        for mods in (["text"], [" text "], ["text"]):
            status, body = _post(
                port,
                "/v1/completions",
                {"model": "mock-planner", "prompt": f"mod {mods!r}", "modalities": mods},
            )
            assert status == 200, (mods, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_still_rejects_non_text_modalities() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {"model": "mock-planner", "prompt": "audio mod", "modalities": ["audio"]},
        )
        assert status == 400, body
        assert "invalid_chat_era_field" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_padded_required_without_tools() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "required pad"}],
                "tool_choice": " required ",
            },
        )
        assert status == 400, body
        assert "invalid_tool_choice" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_padded_tool_choice_none_auto()
    test_http_chat_accepts_padded_function_call_none_auto()
    test_http_completions_accepts_padded_tool_choice_function_call()
    test_http_completions_accepts_modalities_text_as_noop()
    test_http_completions_still_rejects_non_text_modalities()
    test_http_chat_still_rejects_padded_required_without_tools()
    print("ok")
