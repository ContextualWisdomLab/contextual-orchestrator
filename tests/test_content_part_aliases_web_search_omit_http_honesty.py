"""input_text/input_image content aliases and web_search null-nested omit."""

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

_TEST_AUTH_TOKEN = "content_part_aliases_web_search_omit_http_honesty_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )


def _post(port: int, payload: dict) -> tuple[int, dict]:
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


def test_http_chat_accepts_input_text_and_output_text_parts() -> None:
    server, thread, port = _server()
    try:
        for part_type in ("input_text", "INPUT_TEXT", "output_text", " Output_Text "):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": part_type, "text": "hello parts"}],
                        }
                    ],
                },
            )
            assert status == 200, (part_type, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_input_image_parts() -> None:
    server, thread, port = _server()
    try:
        for image_url in (
            "https://example.com/a.png",
            {"url": "https://example.com/a.png"},
            {"url": "https://example.com/a.png", "detail": "AUTO"},
        ):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": "input_image", "image_url": image_url}],
                        }
                    ],
                },
            )
            assert status == 200, (image_url, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_web_search_options_null_nested_omit() -> None:
    server, thread, port = _server()
    try:
        for web in (
            {"user_location": None},
            {"search_context_size": ""},
            {"user_location": None, "search_context_size": "  ", "filters": {}},
        ):
            status, body = _post(
                port,
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"web {web!r}"}],
                    "web_search_options": web,
                },
            )
            assert status == 200, (web, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_web_search_options_with_values() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "web real"}],
                "web_search_options": {"search_context_size": "medium"},
            },
        )
        assert status == 400, body
        assert "invalid_web_search_options" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_unknown_content_part_type() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "input_audio", "input_audio": {"data": "x"}}],
                    }
                ],
            },
        )
        assert status == 400, body
        assert "invalid_message_content" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_accepts_input_text_and_output_text_parts()
    test_http_chat_accepts_input_image_parts()
    test_http_chat_accepts_web_search_options_null_nested_omit()
    test_http_chat_still_rejects_web_search_options_with_values()
    test_http_chat_still_rejects_unknown_content_part_type()
    print("ok")
