"""Full OpenAI passthrough: response_format / tools / the Responses API.

Requests carrying provider features the multi-agent verifier cannot merge are
proxied to one agent per attempt so the full provider response shape survives.
Failed attempts advance to another capability-ranked model or provider.
"""

from __future__ import annotations

import copy
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

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


class _ScriptedPassthroughClient:
    """One-attempt client that fails configured agents for failover tests."""

    def __init__(self, failures: dict[str, Exception]) -> None:
        self.failures = failures
        self.calls: list[tuple[str, str, dict]] = []

    def proxy_send_once(
        self,
        agent: ModelAgent,
        endpoint: str,
        payload: dict,
    ) -> dict:
        """Record one attempt, raise its scripted error, or return tool calls."""
        self.calls.append((agent.id, endpoint, copy.deepcopy(payload)))
        failure = self.failures.get(agent.id)
        if failure is not None:
            raise failure
        return {
            "id": f"chatcmpl_{agent.id}",
            "object": "chat.completion",
            "model": agent.model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": "{}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }


class _LegacyPassthroughClient:
    """Compatibility client exposing only the historical proxy_send method."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def proxy_send(self, agent: ModelAgent, endpoint: str, payload: dict) -> dict:
        """Return a minimal raw response through the compatibility path."""
        self.calls.append((agent.id, endpoint, copy.deepcopy(payload)))
        return {"object": "response", "model": agent.model, "output": []}


def _failover_orchestrator(client: object) -> TaskOrchestrator:
    """Build a deterministic primary/fallback pool for passthrough tests."""
    return TaskOrchestrator(
        agents=[
            ModelAgent(
                "primary_agent",
                "primary-model",
                base_url="mock://primary",
                tags=("coding", "implementation", "reasoning"),
                priority=100,
            ),
            ModelAgent(
                "fallback_agent",
                "fallback-model",
                base_url="mock://fallback",
                tags=("coding", "implementation", "reasoning"),
                priority=90,
            ),
        ],
        client=client,
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


def test_tool_passthrough_moves_to_fallback_after_one_429() -> None:
    rate_limit = urllib.error.HTTPError(
        url="https://provider.invalid/v1/chat/completions",
        code=429,
        msg="Too Many Requests",
        hdrs=None,
        fp=None,
    )
    client = _ScriptedPassthroughClient({"primary_agent": rate_limit})
    orchestrator = _failover_orchestrator(client)
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {}}}]
    body = {
        "messages": [{"role": "user", "content": "inspect this repository"}],
        "tools": tools,
        "tool_choice": "auto",
        "mode": "auto",
    }
    original = copy.deepcopy(body)

    result = orchestrator.proxy_completion(body)

    assert body == original
    assert [call[0] for call in client.calls] == ["primary_agent", "fallback_agent"]
    assert [call[2]["model"] for call in client.calls] == ["primary-model", "fallback-model"]
    assert all(call[2]["tools"] == tools for call in client.calls)
    assert all(call[2]["tool_choice"] == "auto" for call in client.calls)
    assert all(call[2]["stream"] is False for call in client.calls)
    assert all("mode" not in call[2] for call in client.calls)
    assert orchestrator._circuit_open("primary_agent")
    assert result["model"] == "fallback-model"
    assert result["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "lookup"


def test_tool_passthrough_fails_after_each_candidate_once() -> None:
    client = _ScriptedPassthroughClient(
        {
            "primary_agent": ValueError("primary misconfigured"),
            "fallback_agent": ValueError("fallback misconfigured"),
        }
    )
    orchestrator = _failover_orchestrator(client)

    with pytest.raises(RuntimeError, match="all 2 candidate agents failed") as captured:
        orchestrator.proxy_completion(
            {
                "messages": [{"role": "user", "content": "inspect this repository"}],
                "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {}}}],
            }
        )

    assert isinstance(captured.value.__cause__, ValueError)
    assert [call[0] for call in client.calls] == ["primary_agent", "fallback_agent"]
    assert not orchestrator._circuit_open("primary_agent")


def test_passthrough_supports_legacy_client_contract() -> None:
    client = _LegacyPassthroughClient()
    orchestrator = _failover_orchestrator(client)

    result = orchestrator.proxy_completion({"input": "summarize"}, endpoint="responses")

    assert result["object"] == "response"
    assert len(client.calls) == 1
    assert client.calls[0][1] == "responses"
    assert client.calls[0][2]["stream"] is False


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
