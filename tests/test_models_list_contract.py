"""Fixture-aligned unit contracts for OpenAI GET /v1/models pool listing."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "models_list_contract.json"


def _contract() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_models_list_fixture_shape() -> None:
    contract = _contract()
    assert contract["endpoint"]["list_path"] == "/v1/models"
    assert contract["endpoint"]["get_path_template"] == "/v1/models/{model_id}"
    assert contract["list_response"]["object"] == "list"
    assert "id" in contract["list_response"]["data_item_required_keys"]


def test_list_openai_models_matches_enabled_pool_only() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("reasoning",), provider_name="mock_lab"),
            ModelAgent("builder_agent", "mock-builder", tags=("coding",), provider_name="mock_lab"),
            ModelAgent(
                "disabled_agent",
                "mock-disabled",
                tags=("writing",),
                disabled=True,
                provider_name="offline",
            ),
            # Duplicate model id collapses to one list entry.
            ModelAgent("planner_replica", "mock-planner", tags=("reasoning",), provider_name="mock_lab"),
        ]
    )
    payload = orchestrator.list_openai_models()
    contract = _contract()
    assert payload["object"] == contract["list_response"]["object"]
    assert isinstance(payload["data"], list)
    ids = [item["id"] for item in payload["data"]]
    assert ids == ["mock-planner", "mock-builder"]
    for item in payload["data"]:
        for key in contract["list_response"]["data_item_required_keys"]:
            assert key in item, item
        assert item["object"] == "model"
        assert isinstance(item["created"], int)
        assert item["owned_by"] == "mock_lab"


def test_get_openai_model_pool_lookup() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning",), provider_name="local_mock")]
    )
    item = orchestrator.get_openai_model("mock-generalist")
    assert item["id"] == "mock-generalist"
    assert item["object"] == "model"
    assert item["owned_by"] == "local_mock"
    try:
        orchestrator.get_openai_model("text-embedding-3-not-deployed")
        raise AssertionError("expected KeyError for unknown model")
    except KeyError:
        pass


if __name__ == "__main__":
    test_models_list_fixture_shape()
    test_list_openai_models_matches_enabled_pool_only()
    test_get_openai_model_pool_lookup()
    print("ok")
