"""Nested null/blank object omit honesty for unsupported OpenAI controls."""

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

_TEST_AUTH_TOKEN = "nested_null_object_omit_http_honesty_token"  # noqa: S105


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


def test_http_chat_omits_prediction_nested_nulls() -> None:
    server, thread, port = _server()
    try:
        for prediction in (
            {"type": None, "content": None},
            {"content": ""},
            {"type": "  ", "content": None, "extra": {}},
        ):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"pred {prediction!r}"}],
                    "prediction": prediction,
                },
            )
            assert status == 200, (prediction, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_prediction_with_values() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "pred real"}],
                "prediction": {"type": "content", "content": "hello"},
            },
        )
        assert status == 400, body
        assert "invalid_prediction" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_omits_audio_nested_nulls() -> None:
    server, thread, port = _server()
    try:
        for audio in (
            {"voice": None, "format": None},
            {"voice": "", "format": "  "},
            {"voice": None, "format": {}, "extra": {}},
        ):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"audio {audio!r}"}],
                    "audio": audio,
                },
            )
            assert status == 200, (audio, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_audio_with_values() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "audio real"}],
                "audio": {"voice": "alloy", "format": "wav"},
            },
        )
        assert status == 400, body
        assert "invalid_audio" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_omits_tool_resources_nested_nulls() -> None:
    server, thread, port = _server()
    try:
        for tool_resources in (
            {"file_search": None, "code_interpreter": None},
            {"file_search": {}, "code_interpreter": ""},
            {"file_search": None, "code_interpreter": {}},
        ):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"tr {tool_resources!r}"}],
                    "tool_resources": tool_resources,
                },
            )
            assert status == 200, (tool_resources, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_still_rejects_tool_resources_with_values() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tr real"}],
                "tool_resources": {"code_interpreter": {"file_ids": ["f1"]}},
            },
        )
        assert status == 400, body
        assert "invalid_tool_resources" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_omits_reasoning_nested_nulls() -> None:
    server, thread, port = _server()
    try:
        for reasoning in (
            {"effort": None},
            {"effort": "", "summary": None},
            {"effort": "  ", "summary": {}},
        ):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"reason {reasoning!r}"}],
                    "reasoning": reasoning,
                },
            )
            assert status == 200, (reasoning, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_omits_include_null_blank_items() -> None:
    server, thread, port = _server()
    try:
        for include in ([None], [""], [None, "  ", ""], ["", None]):
            status, body = _post(
                port,
                "/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": f"inc {include!r}"}],
                    "include": include,
                },
            )
            assert status == 200, (include, body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_omits_prediction_nested_nulls() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "completions nested prediction",
                "prediction": {"type": None, "content": ""},
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_still_rejects_prediction_with_values() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "completions real prediction",
                "prediction": {"type": "content", "content": "x"},
            },
        )
        assert status == 400, body
        assert "invalid_chat_era_field" in json.dumps(body)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_http_chat_omits_prediction_nested_nulls()
    test_http_chat_still_rejects_prediction_with_values()
    test_http_chat_omits_audio_nested_nulls()
    test_http_chat_still_rejects_audio_with_values()
    test_http_chat_omits_tool_resources_nested_nulls()
    test_http_chat_still_rejects_tool_resources_with_values()
    test_http_chat_omits_reasoning_nested_nulls()
    test_http_chat_omits_include_null_blank_items()
    test_http_completions_omits_prediction_nested_nulls()
    test_http_completions_still_rejects_prediction_with_values()
    print("ok")
