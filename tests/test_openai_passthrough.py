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

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import _responses_to_chat_payload  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server, responses_sse_body  # noqa: E402


def _build() -> TaskOrchestrator:
    return TaskOrchestrator(
        agents=[
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
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
        "model": "mock-planner",
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
    assert "max_tokens" not in result["echo"]
    assert "mode" not in result["echo"]
    assert result["model"] in {"mock-planner", "mock-builder", "mock-reviewer"}


def test_orchestrated_structured_completion_preserves_native_shape_and_lineage() -> None:
    """The HTTP opt-in path conducts evidence before provider-native synthesis."""
    body = {
        "model": "mock-planner",
        "messages": [{"role": "user", "content": "extract JSON"}],
        "response_format": {"type": "json_object"},
    }

    result = _build().proxy_completion(body, single_agent=False)

    assert result["object"] == "chat.completion"
    assert result["echo"]["response_format"] == body["response_format"]
    assert result["orchestration"]["mode"] == "conduct"
    assert result["orchestration"]["agent_count"] == 5


def test_responses_translation_preserves_image_detail() -> None:
    """Responses multimodal input remains available to evidence agents."""
    translated = _responses_to_chat_payload(
        {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "inspect"},
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,AA==",
                            "detail": "high",
                        },
                    ],
                }
            ]
        }
    )

    assert translated["messages"][0]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AA==", "detail": "high"},
    }


def test_proxy_completion_forwards_tools() -> None:
    orch = _build()
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {}}}]
    result = orch.proxy_completion(
        {"model": "mock-planner", "messages": [{"role": "user", "content": "call a tool"}], "tools": tools}
    )
    assert result["echo"]["tools"] == tools


def test_proxy_completion_honors_an_enabled_requested_worker_model() -> None:
    result = _build().proxy_completion({
        "model": "mock-builder",
        "messages": [{"role": "user", "content": "call a tool"}],
        "tools": [],
    })

    assert result["model"] == "mock-builder"


def test_proxy_completion_free_model_uses_only_an_explicitly_free_agent() -> None:
    orch = TaskOrchestrator(
        agents=[
            ModelAgent("paid_agent", "paid-model", priority=100),
            ModelAgent("free_agent", "free-model", tags=("cost:free",)),
        ]
    )

    result = orch.proxy_completion({
        "model": orch.FREE_MODEL,
        "messages": [{"role": "user", "content": "call a tool"}],
        "tools": [],
    })

    assert result["model"] == "free-model"


def test_proxy_completion_free_model_fails_closed_without_a_free_agent() -> None:
    with pytest.raises(RuntimeError, match="no enabled zero-cost model"):
        _build().proxy_completion({
            "model": TaskOrchestrator.FREE_MODEL,
            "messages": [{"role": "user", "content": "call a tool"}],
            "tools": [],
        })


@pytest.mark.parametrize(
    ("endpoint", "body"),
    [
        (
            "chat/completions",
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "return JSON"}],
                "response_format": {"type": "json_object"},
            },
        ),
        (
            "responses",
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "input": "return JSON",
                "text": {"format": {"type": "json_object"}},
            },
        ),
    ],
)
def test_structured_free_model_uses_free_agents_for_evidence_and_synthesis(
    endpoint: str, body: dict,
) -> None:
    """Every conducted call stays inside the explicitly zero-cost pool."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("paid_agent", "paid-model", priority=100),
            ModelAgent("free_agent", "free-model", tags=("cost:free",)),
        ]
    )
    called_agents: list[str] = []
    original_chat = orchestrator.client.chat
    original_proxy = orchestrator.client.proxy_send

    def recording_chat(agent, *args, **kwargs):
        called_agents.append(agent.id)
        return original_chat(agent, *args, **kwargs)

    def recording_proxy(agent, *args, **kwargs):
        called_agents.append(agent.id)
        return original_proxy(agent, *args, **kwargs)

    orchestrator.client.chat = recording_chat  # type: ignore[method-assign]
    orchestrator.client.proxy_send = recording_proxy  # type: ignore[method-assign]

    result = orchestrator.proxy_completion(body, endpoint=endpoint, single_agent=False)

    assert result["orchestration"]["mode"] == "conduct"
    assert called_agents
    assert set(called_agents) == {"free_agent"}


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
    assert "max_tokens" not in result["echo"]


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
                "model": "mock-planner",
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


@pytest.mark.parametrize(
    ("agents", "model", "expected_message"),
    [
        (None, TaskOrchestrator.AUTO_MODEL, "no enabled model"),
        ([ModelAgent("paid_agent", "paid-model")], TaskOrchestrator.FREE_MODEL,
         "no enabled zero-cost model"),
    ],
)
def test_http_structured_virtual_models_reject_ineligible_pools(
    agents: list[ModelAgent] | None, model: str, expected_message: str
) -> None:
    """Structured chat shares the normal virtual-model 400 eligibility boundary."""
    token = "structured_pool_token"
    orchestrator = TaskOrchestrator(
        agents or [ModelAgent("seed_agent", "seed-model")]
    )
    if agents is None:
        orchestrator.agents = []
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = _post(
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": "return JSON"}],
                "response_format": {"type": "json_object"},
            },
            token,
        )
    finally:
        server.shutdown()

    assert status == 400
    assert expected_message in body["error"]["message"]


def test_http_structured_vision_mismatch_remains_a_client_error() -> None:
    """Pool validation does not weaken the existing vision capability boundary."""
    token = "structured_vision_token"
    server = build_server(
        TaskOrchestrator([ModelAgent("text_agent", "text-model")]),
        port=0,
        security=SecurityConfig(auth_token=token),
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = _post(
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
            {
                "model": TaskOrchestrator.AUTO_MODEL,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "inspect"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
                    ],
                }],
                "response_format": {"type": "json_object"},
            },
            token,
        )
    finally:
        server.shutdown()

    assert status == 400
    assert "vision-capable" in body["error"]["message"]


def test_http_responses_endpoint_passes_through() -> None:
    server, port, token = _serve()
    url = f"http://127.0.0.1:{port}/v1/responses"
    try:
        status, body = _post(url, {"model": "mock-planner", "input": "hello"}, token)
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
    # Disabled models are omitted: an inference-scope caller should never see
    # a model it cannot actually call (matches real OpenAI API behavior).
    assert {item["id"] for item in body["data"]} == {
        "contextual-orchestrator", "orchestrator/auto", "mock-planner",
        "mock-builder", "mock-reviewer",
    }


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
        status, body = _post(url, {"model": "mock-planner", "messages": [{"role": "user", "content": "hi"}]}, token)
    finally:
        server.shutdown()
    assert status == 200
    assert body["object"] == "chat.completion"
    assert "echo" not in body  # orchestration path, not passthrough
    assert "orchestration" in body
