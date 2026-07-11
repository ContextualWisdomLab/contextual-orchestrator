"""Full OpenAI passthrough: response_format / tools / the Responses API.

Requests carrying provider features the multi-agent verifier cannot merge are
proxied to one agent so the full provider response shape survives, while plain
prompts keep the orchestration (routing/verification) path.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def _build() -> TaskOrchestrator:
    return TaskOrchestrator(
        agents=[
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation")),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "review")),
        ]
    )


# -- orchestrator-level ------------------------------------------------------

def test_proxy_completion_forwards_response_format_and_returns_full_shape() -> None:
    orch = _build()
    body = {
        "messages": [{"role": "user", "content": "extract JSON"}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "x", "schema": {}}},
        "temperature": 0.1,
        "mode": "auto",  # orchestration-only, must be stripped upstream
    }
    result = orch.proxy_completion(body)

    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["role"] == "assistant"
    # response_format + temperature forwarded; orchestration-only 'mode' stripped.
    assert result["echo"]["response_format"] == body["response_format"]
    assert result["echo"]["temperature"] == 0.1
    assert "mode" not in result["echo"]
    # model overridden to the selected agent's model.
    assert result["model"] in {"mock-planner", "mock-builder", "mock-reviewer"}


def test_proxy_completion_forwards_tools() -> None:
    orch = _build()
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {}}}]
    result = orch.proxy_completion(
        {"messages": [{"role": "user", "content": "call a tool"}], "tools": tools}
    )
    assert result["echo"]["tools"] == tools


def test_proxy_completion_responses_endpoint_returns_response_object() -> None:
    orch = _build()
    result = orch.proxy_completion(
        {"input": "summarize the recording", "response_format": {"type": "text"}},
        endpoint="responses",
    )
    assert result["object"] == "response"
    assert result["output"][0]["role"] == "assistant"
    assert result["echo"]["response_format"] == {"type": "text"}


# -- HTTP server -------------------------------------------------------------

def _post(url: str, payload: dict, token: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}", "connection": "close"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _serve() -> tuple[object, int, str]:
    token = "passthrough_token"
    server = build_server(_build(), port=0, security=SecurityConfig(auth_token=token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1], token


def test_http_chat_completions_accepts_response_format_and_passes_through() -> None:
    server, port, token = _serve()
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    try:
        status, body = _post(
            url,
            {
                "messages": [{"role": "user", "content": "give me JSON"}],
                "response_format": {"type": "json_object"},
            },
            token,
        )
    finally:
        server.shutdown()
    assert status == 200  # previously rejected 400 'unknown_fields'
    assert body["object"] == "chat.completion"
    assert body["echo"]["response_format"] == {"type": "json_object"}


def test_http_responses_endpoint_passes_through() -> None:
    server, port, token = _serve()
    url = f"http://127.0.0.1:{port}/v1/responses"
    try:
        status, body = _post(url, {"input": "hello", "tools": []}, token)
    finally:
        server.shutdown()
    assert status == 200
    assert body["object"] == "response"


def test_http_plain_prompt_still_uses_orchestration_path() -> None:
    server, port, token = _serve()
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    try:
        status, body = _post(url, {"messages": [{"role": "user", "content": "hi"}]}, token)
    finally:
        server.shutdown()
    assert status == 200
    assert body["object"] == "chat.completion"
    assert "echo" not in body  # orchestration path, not passthrough
    assert "orchestration" in body
