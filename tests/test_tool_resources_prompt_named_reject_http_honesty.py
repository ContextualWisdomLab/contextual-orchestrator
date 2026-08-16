"""Named unsupported errors for tool_resources and Responses prompt templates."""

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
    build_server,
    _validate_openai_tool_resources,
    _validate_responses_prompt_template,
)

_TEST_AUTH_TOKEN = "tool_resources_prompt_named_reject_http_honesty_token"  # noqa: S105


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
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_validate_tool_resources_null_and_empty_omit() -> None:
    _validate_openai_tool_resources({"tool_resources": None})
    _validate_openai_tool_resources({"tool_resources": {}})
    _validate_openai_tool_resources({"tool_resources": "  "})


def test_validate_tool_resources_present_fails() -> None:
    try:
        _validate_openai_tool_resources(
            {"tool_resources": {"file_search": {"vector_store_ids": ["vs_1"]}}},
            endpoint_path="/v1/chat/completions",
        )
        raise AssertionError("expected RequestError")
    except RequestError as exc:
        assert exc.code == "invalid_tool_resources"
        assert "not supported" in exc.message


def test_validate_prompt_template_null_empty_omit() -> None:
    _validate_responses_prompt_template({"prompt": None})
    _validate_responses_prompt_template({"prompt": {}})
    _validate_responses_prompt_template({"prompt": ""})


def test_validate_prompt_template_present_fails() -> None:
    try:
        _validate_responses_prompt_template({"prompt": {"id": "pmpt_abc"}})
        raise AssertionError("expected RequestError")
    except RequestError as exc:
        assert exc.code == "invalid_prompt"
        assert "not supported" in exc.message


def test_http_chat_rejects_tool_resources_named() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tool resources"}],
                "tool_resources": {
                    "file_search": {"vector_store_ids": ["vs_1"]},
                },
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_tool_resources" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_chat_accepts_null_tool_resources_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "tool resources null"}],
                "tool_resources": None,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_completions_rejects_tool_resources_named() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/completions",
            {
                "model": "mock-planner",
                "prompt": "legacy tool resources",
                "tool_resources": {"code_interpreter": {"file_ids": ["file_1"]}},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_tool_resources" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_prompt_template_named() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "use prompt template",
                "prompt": {"id": "pmpt_abc", "variables": {"name": "Ada"}},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_prompt" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_rejects_tool_resources_named() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "tool resources on responses",
                "tool_resources": {"file_search": {"vector_store_ids": ["vs_1"]}},
            },
        )
        assert status == 400, body
        blob = json.dumps(body)
        assert "invalid_tool_resources" in blob
        assert "unknown_fields" not in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_responses_accepts_null_prompt_omit() -> None:
    server, thread, port = _server()
    try:
        status, body = _post(
            port,
            "/v1/responses",
            {
                "model": "mock-planner",
                "input": "prompt null omit",
                "prompt": None,
            },
        )
        assert status == 200, body
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_tool_resources_null_and_empty_omit()
    test_validate_tool_resources_present_fails()
    test_validate_prompt_template_null_empty_omit()
    test_validate_prompt_template_present_fails()
    test_http_chat_rejects_tool_resources_named()
    test_http_chat_accepts_null_tool_resources_omit()
    test_http_completions_rejects_tool_resources_named()
    test_http_responses_rejects_prompt_template_named()
    test_http_responses_rejects_tool_resources_named()
    test_http_responses_accepts_null_prompt_omit()
    print("ok")
