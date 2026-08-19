"""Multi-agent provider-shaped requests: response_format / tools / Responses API.

Requests carrying provider features are collected from multiple independent
attempts and synthesized while the full provider response shape survives.
Plain prompts keep the orchestration (routing/verification) path.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server, responses_sse_body  # noqa: E402


def _build() -> TaskOrchestrator:
    return TaskOrchestrator(
        agents=[
            ModelAgent(
                "planner_agent",
                "mock-planner",
                tags=("planning", "reasoning"),
                reasoning_efforts=("high", "xhigh"),
            ),
            ModelAgent("disabled_builder_duplicate", "mock-builder", disabled=True),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation")),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "review")),
            ModelAgent("disabled_candidate", "disabled-model", disabled=True),
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
        "reasoning_effort": "auto",  # orchestrator default, must be omitted upstream
    }
    result = orch.proxy_completion(body)

    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["role"] == "assistant"
    # response_format + temperature forwarded; orchestration-only 'mode' stripped.
    assert result["echo"]["response_format"] == body["response_format"]
    assert result["echo"]["temperature"] == 0.1
    assert "mode" not in result["echo"]
    assert "reasoning_effort" not in result["echo"]
    # model overridden to the selected agent's model.
    assert result["model"] in {"mock-planner", "mock-builder", "mock-reviewer"}


def test_provider_feature_request_always_collects_multiple_attempts() -> None:
    orch = _build()
    calls: list[tuple[str, dict]] = []

    def proxy_send(agent, endpoint, payload):
        calls.append((agent.id, payload))
        return {
            "object": "chat.completion",
            "model": agent.model,
            "choices": [{"message": {"role": "assistant", "content": agent.id}}],
            "echo": {key: payload[key] for key in ("response_format", "model") if key in payload},
        }

    orch.client.proxy_send = proxy_send
    result = orch.proxy_completion({
        "messages": [{"role": "user", "content": "extract JSON"}],
        "response_format": {"type": "json_object"},
        "mode": "auto",
        "reasoning_effort": "auto",
    })

    assert len(calls) == 3  # two independent candidates plus one synthesizer
    assert result["object"] == "chat.completion"
    assert calls[-1][1]["response_format"] == {"type": "json_object"}
    assert "mode" not in calls[-1][1]
    assert "reasoning_effort" not in calls[-1][1]


def test_proxy_completion_forwards_explicit_reasoning_effort() -> None:
    result = _build().proxy_completion(
        {
            "model": "mock-planner",
            "messages": [{"role": "user", "content": "reason carefully"}],
            "reasoning_effort": "high",
        }
    )

    assert result["echo"]["reasoning_effort"] == "high"


def test_proxy_completion_forwards_tools() -> None:
    orch = _build()
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {}}}]
    result = orch.proxy_completion(
        {"messages": [{"role": "user", "content": "call a tool"}], "tools": tools}
    )
    assert result["echo"]["tools"] == tools


def test_proxy_completion_honors_an_enabled_requested_worker_model() -> None:
    result = _build().proxy_completion({
        "model": "mock-builder",
        "messages": [{"role": "user", "content": "call a tool"}],
        "tools": [],
    })

    assert result["model"] == "mock-builder"


def test_proxy_completion_rejects_an_unknown_requested_model() -> None:
    try:
        _build().proxy_completion({
            "model": "not-configured",
            "messages": [{"role": "user", "content": "call a tool"}],
            "tools": [],
        })
    except ValueError as exc:
        assert "not configured" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown explicit model must not silently fall back")


def test_proxy_completion_rejects_disabled_and_malformed_requested_models() -> None:
    with pytest.raises(RuntimeError, match="disabled"):
        _build().proxy_completion({
            "model": "disabled-model",
            "messages": [{"role": "user", "content": "call a tool"}],
        })

    for requested_model in (17, ""):
        with pytest.raises(ValueError, match="non-empty string"):
            _build().proxy_completion({
                "model": requested_model,
                "messages": [{"role": "user", "content": "call a tool"}],
            })


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


def test_http_models_endpoint_lists_configured_models() -> None:
    server, port, token = _serve()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/models",
        headers={"authorization": f"Bearer {token}", "connection": "close"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
    assert status == 200
    assert body["object"] == "list"
    assert {item["id"] for item in body["data"]} == {
        "contextual-orchestrator", "mock-planner", "mock-builder", "mock-reviewer", "disabled-model"
    }
    assert body["data"][0]["kind"] == "orchestrator"
    assert all(item["readiness"] == "unprobed" for item in body["data"])
    assert next(item for item in body["data"] if item["id"] == "mock-builder")["status"] == "active"
    assert next(item for item in body["data"] if item["id"] == "disabled-model")["status"] == "disabled"


def test_responses_stream_has_completion_event() -> None:
    body = {
        "id": "resp_test",
        "object": "response",
        "status": "completed",
        "output": [{
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "OK", "annotations": []}],
        }],
    }
    stream = responses_sse_body(body)
    assert "event: response.output_text.delta" in stream
    assert '"delta": "OK"' in stream
    assert "event: response.completed" in stream
    assert stream.endswith("data: [DONE]\n\n")


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
