from __future__ import annotations

from jsonschema import ValidationError, validate
from pathlib import Path
import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.api_contract import OPENAPI_SPEC  # noqa: E402
from contextual_orchestrator.conventions import is_two_word_snake_case  # noqa: E402


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
