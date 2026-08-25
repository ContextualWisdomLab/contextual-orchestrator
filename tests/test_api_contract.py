from __future__ import annotations

from pathlib import Path
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
    }
    assert expected_paths <= OPENAPI_SPEC["paths"].keys()
    assert "security" not in OPENAPI_SPEC["paths"]["/healthz"]["get"]
    assert OPENAPI_SPEC["paths"]["/v1/chat/completions"]["post"]["security"] == [
        {"inference_bearer_auth": []}
    ]


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


if __name__ == "__main__":  # pragma: no cover
    test_rest_resource_paths_use_two_word_snake_case()
    test_openapi_uses_resource_oriented_operation_ids()
    test_openapi_documents_orchestrator_owned_embedding_model_selection()
    print("ok")
