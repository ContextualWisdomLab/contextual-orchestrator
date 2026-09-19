"""Fail-closed CEFR criterion-observation gateway contract tests."""

from __future__ import annotations

import json
from typing import Any

import pytest

from contextual_orchestrator import (
    CEFR_LANGUAGE_ASSESSMENT_CONTRACT_V1,
    FAST_MLSIRM_SCORING_SCHEMA_VERSION,
    CefrLanguageObservationRequest,
    CefrObservationError,
    CefrRaterAssignment,
    ModelAgent,
    ReasoningEffortProfile,
    TaskOrchestrator,
    TaskOrchestratorCefrGateway,
    observe_language_response_criteria,
)


class _Contract:
    contract_id = CEFR_LANGUAGE_ASSESSMENT_CONTRACT_V1
    fast_mlsirm_contract_version = FAST_MLSIRM_SCORING_SCHEMA_VERSION

    def __init__(self, *, reject_observations: bool = False) -> None:
        self.requests: list[dict[str, Any]] = []
        self.observations: list[dict[str, Any]] = []
        self.reject_observations = reject_observations

    def validate_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(payload)
        return payload

    def validate_observation(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.observations.append(payload)
        assert "cefr_level" not in payload
        assert "score" not in payload
        if self.reject_observations:
            raise CefrObservationError("unsupported_evidence", "observation rejected by test contract")
        return payload


class _Gateway:
    contextual_orchestrator_contract = "contextual-orchestrator-contract-v1"

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.calls: list[dict[str, Any]] = []

    def complete_structured(
        self,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any],
        *,
        api_surface: str,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        envelope = json.loads(messages[1]["content"])
        assignment_ref = envelope["rater_assignment_ref"]
        self.calls.append({"messages": messages, "format": response_format, "surface": api_surface, "model": model_name})
        return {
            "answer": self.answers[assignment_ref],
            "served_agent_id": f"served/{assignment_ref}",
            "model": "mock-rater",
            "provider": "mock-provider",
            "provider_version": "mock-v1",
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "secret": "drop"},
        }


def _request(
    *,
    response_format: str = "json_schema",
    api_surface: str = "chat.completions",
    workflow_settings: dict[str, Any] | None = None,
    assigned_model_name: str | None = None,
) -> CefrLanguageObservationRequest:
    return CefrLanguageObservationRequest(
        task_ref="task/revision-1",
        rubric_ref="rubric/revision-1",
        criterion_ref="writing/coherence",
        category_anchor_refs=("anchor/1", "anchor/2"),
        evidence_reference_ids=("evidence/audio-1", "evidence/transcript-1"),
        rater_assignments=(
            CefrRaterAssignment("rater/b", "llm-family-b", "v2", assigned_model_name),
            CefrRaterAssignment("rater/a", "human-calibration-family", "v1", assigned_model_name),
        ),
        prompt_revision="prompt/revision-1",
        replay_id="replay/1",
        workflow_settings=workflow_settings
        if workflow_settings is not None
        else {"reasoning_effort": "medium", "max_output_tokens": 300},
        response_format=response_format,
        api_surface=api_surface,
    )


def _answer(category: str = "anchor/2", *, uncertainty: str = "low") -> str:
    return json.dumps(
        {
            "criterion_ref": "writing/coherence",
            "category_anchor_ref": category,
            "evidence_reference_ids": ["evidence/transcript-1"],
            "status": "observed",
            "uncertainty": uncertainty,
            "review_signals": [],
            "reason_code": None,
        }
    )


def _abstention(*, uncertainty: str = "low") -> str:
    return json.dumps(
        {
            "criterion_ref": "writing/coherence",
            "category_anchor_ref": None,
            "evidence_reference_ids": [],
            "status": "abstained",
            "uncertainty": uncertainty,
            "review_signals": [],
            "reason_code": "insufficient_evidence",
        }
    )


def test_contract_and_gateway_are_required_before_any_rater_call() -> None:
    request = _request()
    gateway = _Gateway({"rater/a": _answer(), "rater/b": _answer()})
    with pytest.raises(CefrObservationError) as error:
        observe_language_response_criteria(request, gateway, object())
    assert error.value.code == "missing_contract"
    assert gateway.calls == []


def test_independent_raters_are_sorted_blind_and_return_no_final_level() -> None:
    request = _request()
    contract = _Contract()
    gateway = _Gateway({"rater/a": _answer(), "rater/b": _answer()})
    result = observe_language_response_criteria(request, gateway, contract)

    assert [value["assignment_ref"] for value in result["observations"]] == ["rater/a", "rater/b"]
    assert result["human_review"] == {"required": False, "reason_codes": []}
    assert result["panel_size"] == 2
    assert result["observed_count"] == 2
    assert result["incomplete_count"] == 0
    assert result["disagreement_count"] == 0
    assert result["request_replay_identity"] == request.replay_identity
    assert len(contract.observations) == 2
    assert {value["served_agent_id"] for value in result["observations"]} == {"served/rater/a", "served/rater/b"}
    assert all("rater_provenance" in value for value in contract.observations)
    for call in gateway.calls:
        prompt = call["messages"][1]["content"]
        assert "candidate" not in prompt
        assert "rater/a" in prompt or "rater/b" in prompt
        assert "criterion_observation" not in prompt
    serialized = json.dumps(result)
    assert "cefr_level" not in serialized
    assert "placement" not in serialized
    assert "secret" not in serialized


@pytest.mark.parametrize("response_format", ["json_object", "json_schema"])
@pytest.mark.parametrize("api_surface", ["chat.completions", "responses"])
def test_supported_structured_surfaces_are_forwarded(response_format: str, api_surface: str) -> None:
    request = _request(response_format=response_format, api_surface=api_surface)
    gateway = _Gateway({"rater/a": _answer(), "rater/b": _answer()})
    observe_language_response_criteria(request, gateway, _Contract())

    assert {call["surface"] for call in gateway.calls} == {api_surface}
    if response_format == "json_object":
        assert all(call["format"] == {"type": "json_object"} for call in gateway.calls)
    else:
        assert all(call["format"]["type"] == "json_schema" for call in gateway.calls)
        assert all(call["format"]["json_schema"]["strict"] is True for call in gateway.calls)


def test_responses_json_schema_format_includes_required_type() -> None:
    orchestrator = TaskOrchestrator([
        ModelAgent("rater_agent", "mock-rater", tags=("response_format",), base_url="mock://local"),
    ], role_effort_catalog={
        "judge": ReasoningEffortProfile(reasoning_effort="low", max_output_tokens=123),
    })
    observed: dict[str, Any] = {}

    def proxy_send(agent: ModelAgent, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        observed.update({"endpoint": endpoint, "payload": payload})
        return {"output_text": _answer()}

    orchestrator.client.proxy_send = proxy_send  # type: ignore[method-assign]
    TaskOrchestratorCefrGateway(orchestrator).complete_structured(
        [{"role": "user", "content": "opaque references only"}],
        {
            "type": "json_schema",
            "json_schema": {"name": "observation", "schema": {}, "strict": True},
        },
        api_surface="responses",
    )

    assert observed["payload"]["text"]["format"] == {
        "type": "json_schema",
        "name": "observation",
        "schema": {},
        "strict": True,
    }
    assert observed["payload"]["max_output_tokens"] == 123
    assert "max_tokens" not in observed["payload"]
    assert observed["payload"]["reasoning"] == {"effort": "low"}
    assert "reasoning_effort" not in observed["payload"]


def test_disagreement_and_high_uncertainty_route_to_human_review() -> None:
    request = _request()
    gateway = _Gateway({"rater/a": _answer("anchor/1", uncertainty="high"), "rater/b": _answer()})
    result = observe_language_response_criteria(request, gateway, _Contract())

    assert result["human_review"]["required"] is True
    assert result["human_review"]["reason_codes"] == ["disagreement", "uncertain"]
    assert result["disagreement_count"] == 1


def test_duplicate_json_is_failed_without_provider_text_leaking() -> None:
    request = _request()
    duplicate = '{"criterion_ref":"writing/coherence","criterion_ref":"leak-me"}'
    gateway = _Gateway({"rater/a": duplicate, "rater/b": _answer()})
    result = observe_language_response_criteria(request, gateway, _Contract())

    failed = next(value for value in result["observations"] if value["assignment_ref"] == "rater/a")
    assert failed["failure_code"] == "malformed_json"
    assert failed["criterion_observation"] is None
    assert "leak-me" not in json.dumps(result)
    assert result["human_review"]["required"] is True
    assert result["incomplete_count"] == 1


def test_verifier_failure_preserves_successful_parse_state() -> None:
    request = _request()
    gateway = _Gateway({"rater/a": _answer(), "rater/b": _answer()})
    result = observe_language_response_criteria(request, gateway, _Contract(reject_observations=True))

    failed = result["observations"][0]
    assert failed["parse_state"] == "accepted"
    assert failed["verifier_state"] == "rejected"
    assert failed["failure_code"] == "unsupported_evidence"


def test_served_model_must_match_an_explicit_rater_assignment() -> None:
    request = _request(assigned_model_name="assigned-model")
    gateway = _Gateway({"rater/a": _answer(), "rater/b": _answer()})
    result = observe_language_response_criteria(request, gateway, _Contract())

    assert all(value["failure_code"] == "rater_assignment_mismatch" for value in result["observations"])


def test_abstention_does_not_count_as_category_disagreement() -> None:
    request = _request()
    gateway = _Gateway({"rater/a": _abstention(), "rater/b": _answer()})
    result = observe_language_response_criteria(request, gateway, _Contract())

    assert "disagreement" not in result["human_review"]["reason_codes"]
    assert "incomplete_observation_panel" in result["human_review"]["reason_codes"]
    assert result["observed_count"] == 1
    assert result["incomplete_count"] == 1


def test_workflow_settings_are_deeply_immutable_and_serializable() -> None:
    settings = {"nested": {"limit": 1}, "items": ["a"]}
    request = _request(workflow_settings=settings)
    settings["nested"]["limit"] = 99
    settings["items"].append("b")

    assert request.workflow_settings["nested"]["limit"] == 1
    assert request.workflow_settings["items"] == ("a",)
    assert request.to_contract_payload()["workflow_settings"] == {
        "nested": {"limit": 1},
        "items": ["a"],
    }


def test_request_rejects_duplicate_or_missing_opaque_references() -> None:
    with pytest.raises(CefrObservationError, match="must not contain duplicates"):
        _request().__class__(
            task_ref="task/1",
            rubric_ref="rubric/1",
            criterion_ref="criterion/1",
            category_anchor_refs=("anchor/1", "anchor/1"),
            evidence_reference_ids=("evidence/1",),
            rater_assignments=(CefrRaterAssignment("rater/1", "family/1", "v1"),),
            prompt_revision="prompt/1",
            replay_id="replay/1",
            workflow_settings={},
        )


def test_task_orchestrator_adapter_uses_structured_capability_and_responses_shape() -> None:
    orchestrator = TaskOrchestrator([
        ModelAgent("rater_agent", "mock-rater", tags=("response_format",), base_url="mock://local"),
    ])
    observed: dict[str, Any] = {}

    def proxy_send(agent: ModelAgent, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        observed.update({"agent": agent.id, "endpoint": endpoint, "payload": payload})
        if endpoint == "responses":
            return {"output_text": _answer()}
        return {"choices": [{"message": {"content": _answer()}}]}

    orchestrator.client.proxy_send = proxy_send  # type: ignore[method-assign]
    gateway = TaskOrchestratorCefrGateway(orchestrator)
    response = gateway.complete_structured(
        [{"role": "user", "content": "opaque references only"}],
        {"type": "json_object"},
        api_surface="responses",
    )

    assert response["served_agent_id"] == "rater_agent"
    assert observed["endpoint"] == "responses"
    assert observed["payload"]["text"] == {"format": {"type": "json_object"}}
