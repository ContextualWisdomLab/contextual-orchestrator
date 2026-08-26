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
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    ModelClient,
    NoViableAgentError,
    validate_json_schema_contract,
)
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _validate_chat_response_format,
    build_server,
    responses_sse_body,
)


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
    # model overridden to the selected agent's model.
    assert result["model"] in {"mock-planner", "mock-builder", "mock-reviewer"}


def test_virtual_json_schema_uses_conduct_and_plain_chat_repair() -> None:
    """Virtual schema work must never use provider-native passthrough."""

    calls: list[str] = []

    class PlainChatRepair(ModelClient):
        def proxy_send(self, agent, endpoint, body):  # type: ignore[override]
            raise AssertionError("virtual json_schema must not use native passthrough")

        def chat(self, agent, messages, **kwargs):  # type: ignore[override]
            del messages, kwargs
            calls.append(agent.id)
            return '{"cases":[]}' if len(calls) >= 5 else "synthesized evidence"

    agents = [
        ModelAgent("ready_a", "mock-a", tags=("reasoning",)),
        ModelAgent("ready_b", "mock-b", tags=("reasoning",)),
    ]
    orchestrator = TaskOrchestrator(agents, client=PlainChatRepair())
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "operations_case_evidence",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"cases": {"type": "array"}},
                "required": ["cases"],
                "additionalProperties": False,
            },
        },
    }

    result = orchestrator.run_structured(
        [{"role": "user", "content": "synthetic evidence"}],
        response_format=schema,
        model_name=orchestrator.AUTO_MODEL,
    )

    assert len(calls) >= 5
    assert json.loads(result["answer"]) == {"cases": []}
    assert result["trace"][-1]["role"] == "structured_repair"


def test_virtual_structured_repair_defers_when_all_candidates_return_invalid_json() -> None:
    """All invalid repairs return typed admission deferral."""

    calls: list[str] = []

    class InvalidRepair(ModelClient):
        def proxy_send(self, agent, endpoint, body):  # type: ignore[override]
            raise AssertionError("virtual json_schema must not use native passthrough")

        def chat(self, agent, messages, **kwargs):  # type: ignore[override]
            del messages, kwargs
            calls.append(agent.id)
            return "not json"

    agents = [ModelAgent(f"ready_{index}", "mock", tags=("reasoning",)) for index in range(2)]
    orchestrator = TaskOrchestrator(agents, client=InvalidRepair())

    with pytest.raises(NoViableAgentError):
        orchestrator.run_structured(
            [{"role": "user", "content": "synthetic evidence"}],
            model_name=orchestrator.AUTO_MODEL,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "operations_case_evidence", "schema": {"type": "object"}},
            },
        )

    assert len(calls) >= 2


def test_structured_readiness_uses_minimal_schema_workflow_not_native_surface() -> None:
    calls: list[str] = []

    class PlainOnly(ModelClient):
        def proxy_send(self, agent, endpoint, body):  # type: ignore[override]
            raise AssertionError("readiness must not use native response_format")

        def chat(self, agent, messages, **kwargs):  # type: ignore[override]
            del messages, kwargs
            calls.append(agent.id)
            return '{"ok":true}'

    unprobed = ModelAgent("unprobed_primary", "mock")
    agent = ModelAgent("plain_only", "mock")
    result = TaskOrchestrator([unprobed, agent], client=PlainOnly()).probe_structured_workflow(agent)

    assert result["status"] == "ready"
    assert len(calls) > 1
    assert set(calls) == {"plain_only"}


def test_json_schema_contract_accepts_nullable_enum_and_rejects_unknown_keyword() -> None:
    validate_json_schema_contract(
        {
            "type": "object",
            "properties": {
                "kind": {"type": ["string", "null"], "enum": ["fact", None]},
                "items": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["kind", "items"],
            "additionalProperties": False,
        }
    )
    with pytest.raises(ValueError, match="unsupported keyword"):
        validate_json_schema_contract({"type": "object", "madeUpKeyword": True})

    with pytest.raises(RequestError) as error:
        _validate_chat_response_format(
            {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "invalid_schema",
                        "schema": {"type": "object", "madeUpKeyword": True},
                    },
                }
            }
        )
    assert error.value.code == "invalid_response_format"


def test_structured_passthrough_does_not_call_unadmitted_primary() -> None:
    """A virtual request must start with a capability-admitted candidate."""

    calls: list[str] = []

    class Recorder(ModelClient):
        def proxy_send(self, agent, endpoint, body):  # type: ignore[override]
            del endpoint
            calls.append(agent.id)
            return {"model": agent.model, "echo": body}

    orchestrator = TaskOrchestrator(
        [
            ModelAgent("unready_primary", "mock-unready"),
            ModelAgent("ready_fallback", "mock-ready"),
        ],
        client=Recorder(),
    )
    orchestrator._structured_admitted_agent_ids = lambda: {"ready_fallback"}  # type: ignore[method-assign]

    result = orchestrator.proxy_completion(
        {
            "model": orchestrator.AUTO_MODEL,
            "messages": [{"role": "user", "content": "synthetic evidence"}],
            "response_format": {"type": "json_object"},
        }
    )

    assert calls == ["ready_fallback"]
    assert result["model"] == "mock-ready"


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


def test_proxy_completion_free_model_never_fails_over_to_a_paid_agent() -> None:
    """A zero-cost request remains zero-cost when its ready provider fails."""

    calls: list[str] = []

    class FreeDown(ModelClient):
        def proxy_send(self, agent, endpoint, body):  # type: ignore[override]
            del endpoint, body
            calls.append(agent.id)
            raise RuntimeError("provider transport unavailable")

    orchestrator = TaskOrchestrator(
        agents=[
            ModelAgent("free_agent", "mock-free", tags=("cost:free",)),
            ModelAgent("paid_agent", "mock-paid"),
        ],
        client=FreeDown(),
    )

    with pytest.raises(NoViableAgentError):
        orchestrator.proxy_completion(
            {
                "model": orchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "synthetic request"}],
                "response_format": {"type": "json_object"},
            }
        )

    assert calls == ["free_agent"]


def test_proxy_completion_free_model_fails_closed_without_a_free_agent() -> None:
    with pytest.raises(RuntimeError, match="no enabled zero-cost model"):
        _build().proxy_completion({
            "model": TaskOrchestrator.FREE_MODEL,
            "messages": [{"role": "user", "content": "call a tool"}],
            "tools": [],
        })


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


def _post_error_with_headers(
    url: str, payload: dict, token: str
) -> tuple[int, dict, dict[str, str]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "connection": "close",
        },
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request, timeout=5)
    exc = exc_info.value
    return (
        exc.code,
        json.loads(exc.read().decode("utf-8")),
        dict(exc.headers.items()),
    )


def _serve() -> tuple[object, int, str]:
    token = "passthrough_token"
    server = build_server(_build(), port=0, security=SecurityConfig(auth_token=token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1], token


def test_http_structured_no_viable_agent_exposes_retry_contract() -> None:
    """A structured readiness miss is retryable without hiding as a 504."""
    orchestrator = _build()
    token = "passthrough_token"
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
    try:
        with patch.object(
            orchestrator,
            "proxy_completion",
            side_effect=NoViableAgentError(retry_after_seconds=30),
        ):
            status, body, headers = _post_error_with_headers(
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
        server.server_close()

    assert status == 503
    assert body["error"]["code"] == "no_viable_agent"
    assert body["error"]["detail"]["retry_after_seconds"] == 30
    assert headers["Retry-After"] == "30"


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


def test_http_virtual_json_schema_preserves_openai_shape_and_orchestration_lineage() -> None:
    class PlainStructured(ModelClient):
        def proxy_send(self, agent, endpoint, body):  # type: ignore[override]
            raise AssertionError("virtual json_schema must not use native passthrough")

        def chat(self, agent, messages, **kwargs):  # type: ignore[override]
            del agent, messages, kwargs
            return '{"cases":[]}'

    orchestrator = TaskOrchestrator(
        [ModelAgent("plain_agent", "mock", tags=("reasoning",))],
        client=PlainStructured(),
    )
    token = "structured_token"
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = _post(
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
            {
                "model": orchestrator.AUTO_MODEL,
                "messages": [{"role": "user", "content": "synthetic evidence"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "operations_case_evidence",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {"cases": {"type": "array"}},
                            "required": ["cases"],
                            "additionalProperties": False,
                        },
                    },
                },
            },
            token,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert body["object"] == "chat.completion"
    assert json.loads(body["choices"][0]["message"]["content"]) == {"cases": []}
    assert body["orchestration"]["mode"] == "conduct"
    assert body["orchestration"]["usage_record_id"]


def test_http_responses_endpoint_passes_through() -> None:
    server, port, token = _serve()
    url = f"http://127.0.0.1:{port}/v1/responses"
    try:
        status, body = _post(url, {"model": "mock-planner", "input": "hello"}, token)
    finally:
        server.shutdown()
    assert status == 200
    assert body["object"] == "response"


def test_http_responses_applies_deadline_to_passthrough_and_orchestration() -> None:
    token = "responses_deadline_token"
    orchestrator = _build()
    observed: list[tuple[str, float | None]] = []
    original_proxy = orchestrator.proxy_completion
    original_complete = orchestrator.complete
    original_stream_route = orchestrator.stream_route
    original_conduct = orchestrator.conduct
    original_would_route = orchestrator.would_route

    def proxy(*args, **kwargs):
        observed.append(("proxy", orchestrator.client.request_settings_snapshot()["request_deadline_monotonic"]))
        return original_proxy(*args, **kwargs)

    def complete(*args, **kwargs):
        observed.append(("complete", orchestrator.client.request_settings_snapshot()["request_deadline_monotonic"]))
        return original_complete(*args, **kwargs)

    def stream_route(*args, **kwargs):
        observed.append(("stream", orchestrator.client.request_settings_snapshot()["request_deadline_monotonic"]))
        return original_stream_route(*args, **kwargs)

    def conduct(*args, **kwargs):
        observed.append(("conduct", orchestrator.client.request_settings_snapshot()["request_deadline_monotonic"]))
        return original_conduct(*args, **kwargs)

    def would_route(messages, mode, model_name):
        if messages[-1]["content"] in {"direct stream", "conduct stream"}:
            return messages[-1]["content"] == "direct stream"
        return original_would_route(messages, mode, model_name)

    orchestrator.proxy_completion = proxy  # type: ignore[method-assign]
    orchestrator.complete = complete  # type: ignore[method-assign]
    orchestrator.stream_route = stream_route  # type: ignore[method-assign]
    orchestrator.conduct = conduct  # type: ignore[method-assign]
    orchestrator.would_route = would_route  # type: ignore[method-assign]
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/v1/responses"

    def post(payload: dict) -> None:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {token}",
                "x-request-timeout-ms": "180000",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
            response.read()

    try:
        post({"model": "mock-planner", "input": "hello"})
        post({"model": "orchestrator/auto", "input": "hello"})
        post({"model": "orchestrator/auto", "input": "direct stream", "stream": True})
        post({"model": "orchestrator/auto", "input": "conduct stream", "stream": True})
    finally:
        server.shutdown()

    assert {kind for kind, _deadline in observed} == {"proxy", "complete", "stream", "conduct"}
    assert all(deadline is not None for _kind, deadline in observed)


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
