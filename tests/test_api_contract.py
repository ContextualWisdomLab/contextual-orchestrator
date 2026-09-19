from __future__ import annotations

from contextlib import contextmanager
from jsonschema import ValidationError, validate
from pathlib import Path
import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataclasses import replace

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.api_contract import OPENAPI_SPEC  # noqa: E402
from contextual_orchestrator.conventions import is_two_word_snake_case  # noqa: E402
from contextual_orchestrator.orchestrator import chat_completion_response  # noqa: E402
from contextual_orchestrator.provider_errors import ProviderUpstreamError  # noqa: E402


def test_rest_resource_paths_use_two_word_snake_case() -> None:
    for path in OPENAPI_SPEC["paths"]:
        if not path.startswith("/api/v1/"):
            continue  # pragma: no cover
        segment = path.removeprefix("/api/v1/").split("/", 1)[0]
        assert is_two_word_snake_case(segment.rstrip("s")), path


def test_openapi_uses_resource_oriented_operation_ids() -> None:
    operation_ids = []
    for path_item in OPENAPI_SPEC["paths"].values():
        for operation in path_item.values():
            operation_ids.append(operation["operationId"])

    assert "list_agent_pools" in operation_ids
    assert "create_workflow_run" in operation_ids
    assert "get_workflow_run" in operation_ids
    assert "get_access_report" in operation_ids
    assert "patch_worker_agent" in operation_ids
    assert "create_evaluation_run" in operation_ids
    assert all(is_two_word_snake_case(operation_id) for operation_id in operation_ids)


def test_openapi_documents_compatibility_front_door() -> None:
    expected_paths = {
        "/openapi.json",
        "/healthz",
        "/v1/models",
        "/v1/models/{model_id}",
        "/v1/chat/completions",
        "/v1/completions",
        "/v1/embeddings",
        "/v1/responses",
        "/v1/batch/embeddings",
        "/v1/batch/embeddings/{batch_id}",
        "/v1/videos/{video_job_id}",
        "/v1/videos/{video_job_id}/content",
    }
    assert expected_paths <= OPENAPI_SPEC["paths"].keys()
    assert "security" not in OPENAPI_SPEC["paths"]["/healthz"]["get"]
    assert OPENAPI_SPEC["paths"]["/v1/chat/completions"]["post"]["security"] == [
        {"inference_bearer_auth": []}
    ]
    chat_schema = OPENAPI_SPEC["paths"]["/v1/chat/completions"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]
    assert chat_schema["properties"]["include_orchestration_trace"]["type"] == "boolean"
    chat_response = OPENAPI_SPEC["components"]["schemas"]["ChatCompletionResponse"]
    assert chat_response["properties"]["usage"]["$ref"].endswith("AuthoritativeUsage")
    assert chat_response["properties"]["usage_measurement_status"]["enum"] == [
        "measured",
        "unavailable",
    ]
    measured, unavailable = chat_response["oneOf"]
    assert measured["properties"]["usage_measurement_status"] == {"const": "measured"}
    assert measured["properties"]["usage"]["required"] == [
        "prompt_tokens",
        "completion_tokens",
    ]
    assert unavailable["properties"]["usage_measurement_status"] == {
        "const": "unavailable"
    }
    assert unavailable["properties"]["usage"] == {"type": "null"}
    assert OPENAPI_SPEC["paths"]["/api/v1/access_reports/{workflow_run_id}"]["get"][
        "security"
    ] == [{"admin_bearer_auth": [], "trace_bearer_auth": []}]
    patch_schema = OPENAPI_SPEC["paths"][
        "/api/v1/agent_pools/{agent_pool_id}/worker_agents/{worker_agent_id}"
    ]["patch"]["requestBody"]["content"]["application/json"]["schema"]
    assert patch_schema["properties"]["stream_usage_supported"]["type"] == "boolean"
    assert patch_schema["properties"]["max_output_tokens"]["anyOf"] == [
        {
            "type": "integer",
            "minimum": 1,
            "maximum": 9_223_372_036_854_775_807,
        },
        {"type": "null"},
    ]
    assert patch_schema["properties"]["context_window"]["anyOf"] == [
        {
            "type": "integer",
            "minimum": 1,
            "maximum": 9_223_372_036_854_775_807,
        },
        {"type": "null"},
    ]
    assert OPENAPI_SPEC["components"]["securitySchemes"]["trace_bearer_auth"]["scheme"] == (
        "bearer"
    )
    assert OPENAPI_SPEC["paths"]["/api/v1/batch_routing_jobs/{batch_routing_job_id}/results"]["post"][
        "security"
    ] == [{"inference_bearer_auth": [], "trace_bearer_auth": []}]


def test_openapi_documents_orchestrator_owned_embedding_model_selection() -> None:
    embeddings_schema = OPENAPI_SPEC["paths"]["/v1/embeddings"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    batch_schema = OPENAPI_SPEC["paths"]["/v1/batch/embeddings"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]

    assert embeddings_schema["required"] == ["input"]
    assert "503" in OPENAPI_SPEC["paths"]["/v1/embeddings"]["post"]["responses"]
    assert "model" not in batch_schema.get("required", [])
    assert "503" in OPENAPI_SPEC["paths"]["/v1/batch/embeddings"]["post"]["responses"]
    assert "Optional enabled embedding-capable pool model" in embeddings_schema["properties"]["model"][
        "description"
    ]


def test_openapi_omitted_text_models_match_runtime_contract() -> None:
    """Omitted text models validate while explicit null still fails the schema."""
    for path, payload in (
        ("/v1/chat/completions", {"messages": [{"role": "user", "content": "hi"}]}),
        ("/v1/completions", {"prompt": "hi"}),
        ("/v1/responses", {"input": "hi"}),
    ):
        schema = OPENAPI_SPEC["paths"][path]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        assert "model" not in schema.get("required", [])
        validate(payload, schema)
        with pytest.raises(ValidationError):
            validate({**payload, "model": None}, schema)


def test_openapi_capability_requests_have_endpoint_specific_contracts() -> None:
    expected_required = {
        "/v1/images/generations": ["prompt"],
        "/v1/videos": ["prompt"],
        "/v1/audio/speech": ["input", "voice"],
        "/v1/audio/transcriptions": ["input_audio"],
        "/v1/rerank": ["query", "documents"],
        "/v1/audio/generations": ["messages"],
    }
    for path, required in expected_required.items():
        schema = OPENAPI_SPEC["paths"][path]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        assert schema["required"] == required
        assert schema["properties"]["zdr_only"]["type"] == "boolean"


if __name__ == "__main__":  # pragma: no cover
    test_rest_resource_paths_use_two_word_snake_case()
    test_openapi_uses_resource_oriented_operation_ids()
    test_openapi_documents_orchestrator_owned_embedding_model_selection()
    print("ok")



def test_batch_job_openapi_documents_principal_hiding_404s() -> None:
    """Missing and foreign batch jobs share the documented not-found surface."""
    status = OPENAPI_SPEC["paths"][
        "/api/v1/batch_routing_jobs/{batch_routing_job_id}"
    ]["get"]["responses"]
    results = OPENAPI_SPEC["paths"][
        "/api/v1/batch_routing_jobs/{batch_routing_job_id}/results"
    ]["post"]["responses"]
    assert "404" in status
    assert "not owned" in status["404"]["description"]
    assert results["404"] == status["404"]


# --- issue #1016 rows 2/4: orchestration.route/attempts is a stable, typed
# adapter contract shared by the structured-synthesis and single-worker
# streaming fallback paths. These fixtures are intentionally minimal test
# doubles (not the full HTTP server) so both paths can be exercised directly
# through their real orchestration code.

_JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "review_verdict",
        "schema": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
        "strict": True,
    },
}


def _free_agents() -> list:
    return [
        ModelAgent(
            "primary_free_agent",
            "primary-free-model",
            priority=10,
            provider_name="primary",
            tags=("cost:free", "reasoning", "coding"),
        ),
        ModelAgent(
            "fallback_free_agent",
            "fallback-free-model",
            priority=1,
            provider_name="fallback",
            tags=("cost:free", "reasoning", "coding"),
        ),
    ]


class _StructuredFailThenServeClient:
    """Minimal structured-synthesis double: first candidate 502s, second serves."""

    def __init__(self) -> None:
        self._settings: dict = {}

    def request_settings_snapshot(self) -> dict:
        return {
            "temperature": None,
            "top_p": None,
            "presence_penalty": None,
            "frequency_penalty": None,
            "max_output_tokens": 256,
            **self._settings,
        }

    @contextmanager
    def request_settings(self, **overrides):
        previous = dict(self._settings)
        self._settings.update({key: value for key, value in overrides.items() if value is not None})
        try:
            yield
        finally:
            self._settings = previous

    @contextmanager
    def suppress_request_tools(self):
        previous = dict(self._settings)
        for key in ("tools", "tool_choice", "parallel_tool_calls"):
            self._settings.pop(key, None)
        try:
            yield
        finally:
            self._settings = previous

    def chat(self, agent, messages, **kwargs) -> str:  # noqa: ANN001 - test double
        del agent, messages, kwargs
        return "paper-role-output"

    def take_usage(self) -> None:
        return None

    def proxy_send(self, agent, endpoint, payload) -> dict:  # noqa: ANN001 - test double
        del endpoint, payload
        if agent.id.startswith("primary_"):
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="api_error",
                message="provider rejected the request with HTTP 502",
                client_status=502,
                provider_status=502,
                retryable=True,
                transport="structured_synthesis",
            )
        return {
            "id": "chatcmpl-fallback",
            "object": "chat.completion",
            "model": agent.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": '{"ok": true}'},
                    "finish_reason": "stop",
                }
            ],
        }

    def proxy_send_once(self, agent, endpoint, payload) -> dict:  # noqa: ANN001 - test double
        return self.proxy_send(agent, endpoint, payload)


class _StreamFailThenServeClient:
    """Minimal streaming double: first candidate's ``stream_chat`` raises."""

    def stream_chat(self, agent, messages, **kwargs):  # noqa: ANN001 - test double
        del messages, kwargs
        if agent.id == "primary_worker":
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="service_unavailable",
                message="provider rejected the request with HTTP 503",
                client_status=503,
                provider_status=503,
                retryable=True,
                transport="stream",
            )
        yield "served output"

    def take_usage(self) -> None:
        return None


def _stream_failover_agents() -> list:
    return [
        ModelAgent("primary_worker", "primary-model", priority=10, tags=("reasoning", "writing")),
        ModelAgent("fallback_worker", "fallback-model", priority=1, tags=("reasoning", "writing")),
    ]


def test_orchestration_route_schema_validates_structured_synthesis_fallback() -> None:
    """A real structured-synthesis failover's route validates against the contract."""
    orchestrator = TaskOrchestrator(_free_agents(), client=_StructuredFailThenServeClient())
    result = orchestrator.proxy_completion(
        {
            "model": TaskOrchestrator.FREE_MODEL,
            "messages": [{"role": "user", "content": "return a json verdict"}],
            "response_format": _JSON_SCHEMA,
        },
        single_agent=False,
    )
    route = result["orchestration"]["route"]
    schema = OPENAPI_SPEC["components"]["schemas"]["OrchestrationRoute"]
    validate(route, {**schema, "components": OPENAPI_SPEC["components"]})
    outcomes = [attempt["outcome"] for attempt in route["attempted"]]
    assert outcomes == ["retryable_transport", "served"]


def test_orchestration_route_attempt_schema_validates_streaming_fallback() -> None:
    """A real streaming single-worker failover's typed attempt matches the contract."""
    orchestrator = TaskOrchestrator(_stream_failover_agents(), client=_StreamFailThenServeClient())
    answer = "".join(
        orchestrator.stream_route([{"role": "user", "content": "stream this"}])
    )
    assert answer == "served output"
    trace = next(iter(orchestrator._workflow_runs.values()))["trace"]
    schema = OPENAPI_SPEC["components"]["schemas"]["OrchestrationRouteAttempt"]
    failed_attempt = {
        key: trace[0][key]
        for key in ("agent_id", "model", "outcome", "error_code", "provider_status", "retryable", "transport")
    }
    validate(failed_attempt, {**schema, "components": OPENAPI_SPEC["components"]})
    assert failed_attempt["outcome"] == "retryable_transport"


class _RouteOnceFailThenServeClient:
    """Minimal non-streaming double: first candidate's ``chat`` raises, second serves."""

    def chat(self, agent, messages, **kwargs):  # noqa: ANN001 - test double
        del messages, kwargs
        if agent.id == "primary_worker":
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="service_unavailable",
                message="provider rejected the request with HTTP 503",
                client_status=503,
                provider_status=503,
                retryable=True,
                transport="chat",
            )
        return "served by fallback"

    def take_usage(self) -> None:
        return None


def test_orchestration_route_schema_validates_route_once_failover() -> None:
    """A real non-streaming route_once failover's route validates against the contract."""
    orchestrator = TaskOrchestrator(
        _stream_failover_agents(), client=_RouteOnceFailThenServeClient()
    )
    # Mechanical failover only — judge traffic would obscure typed attempt rows.
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    result = orchestrator.route_once([{"role": "user", "content": "route this"}])
    assert result["answer"] == "served by fallback"
    route = result["route"]
    schema = OPENAPI_SPEC["components"]["schemas"]["OrchestrationRoute"]
    validate(route, {**schema, "components": OPENAPI_SPEC["components"]})
    outcomes = [attempt["outcome"] for attempt in route["attempted"]]
    assert outcomes == ["retryable_transport", "served"]
    assert route["terminal_reason"] == "served"
    body = chat_completion_response(result, include_trace=True)
    assert body["orchestration"]["route"] == route
    assert body["orchestration"]["route"]["attempted"][0]["outcome"] == "retryable_transport"


def test_route_once_success_on_first_attempt_omits_route_evidence() -> None:
    """A clean first-try route_once response must not invent failed attempt rows."""

    class _ServeFirstClient:
        def chat(self, agent, messages, **kwargs):  # noqa: ANN001 - test double
            del messages, kwargs
            return "first-try answer"

        def take_usage(self) -> None:
            return None

    orchestrator = TaskOrchestrator(
        _stream_failover_agents()[:1],
        client=_ServeFirstClient(),
    )
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    result = orchestrator.route_once([{"role": "user", "content": "route this"}])
    assert result["answer"] == "first-try answer"
    assert "route" not in result
    response = chat_completion_response(result)
    assert "route" not in response.get("orchestration", {})


def test_route_once_preserves_worker_failover_evidence_across_realtime_judge() -> None:
    """The judge's nested invoke must not clear the worker's route evidence."""

    class _WorkerFailoverThenJudgeClient:
        worker_served = False

        def chat(self, agent, messages, **kwargs):  # noqa: ANN001 - test double
            del messages, kwargs
            if not self.worker_served and agent.id == "primary_worker":
                raise ProviderUpstreamError(
                    agent_id=agent.id,
                    model=agent.model,
                    error_code="service_unavailable",
                    message="provider rejected the worker request with HTTP 503",
                    client_status=503,
                    provider_status=503,
                    retryable=True,
                    transport="chat",
                )
            self.worker_served = True
            return "served output"

        def take_usage(self) -> None:
            return None

    orchestrator = TaskOrchestrator(
        _stream_failover_agents(), client=_WorkerFailoverThenJudgeClient()
    )

    def nested_judge(**kwargs):  # noqa: ANN003 - mirrors the owned judge boundary
        del kwargs
        orchestrator._invoke(
            orchestrator.agents[0],
            [{"role": "user", "content": "judge the worker answer"}],
            text="judge the worker answer",
            role="worker",
        )
        return {
            "accepted": True,
            "reason": "judge accepted",
            "verifier_output": "served output",
            "judge": "model",
        }

    orchestrator._realtime_route_judge = nested_judge  # type: ignore[method-assign]

    result = orchestrator.route_once([{"role": "user", "content": "route this"}])

    assert result["answer"] == "served output"
    assert [attempt["outcome"] for attempt in result["route"]["attempted"]] == [
        "retryable_transport",
        "served",
    ]
