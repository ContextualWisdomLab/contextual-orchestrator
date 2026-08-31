"""Tests for the domain-neutral governed rater observation context."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from contextual_orchestrator.rater_observation import (
    GOVERNED_RATER_OBSERVATION_CONTRACT_V1,
    GOVERNED_RATER_CONFORMANCE_SHA256,
    GOVERNED_RATER_SCHEMA_SHA256,
    GOVERNED_RATER_UPSTREAM_REVISION,
    MAX_RATER_EVIDENCE_REFERENCES,
    MAX_RATER_OBSERVATIONS,
    MAX_RATER_REFERENCE_LENGTH,
    MAX_RATER_REVIEW_SIGNALS,
    CriterionObservation,
    RaterConfigurationIdentity,
    RaterInvocation,
    RaterObservationError,
)


def _configuration() -> dict[str, str]:
    return {
        "rater_family_ref": "model-family",
        "provider_ref": "provider",
        "implementation_revision_ref": "model-revision",
        "instruction_revision_ref": "prompt-revision",
        "response_schema_revision_ref": "schema-revision",
        "workflow_mode_ref": "blind-independent",
        "modality_channel_ref": "text",
    }


def _observed(criterion_ref: str = "criterion-a") -> dict[str, object]:
    return {
        "criterion_ref": criterion_ref,
        "status": "observed",
        "category_anchor_ref": "category-2",
        "evidence_reference_ids": ["evidence-1"],
        "uncertainty": "medium",
        "review_signal_refs": [],
        "reason_ref": None,
    }


def _abstained(criterion_ref: str = "criterion-b") -> dict[str, object]:
    return {
        "criterion_ref": criterion_ref,
        "status": "abstained",
        "category_anchor_ref": None,
        "evidence_reference_ids": [],
        "uncertainty": "high",
        "review_signal_refs": ["human-review"],
        "reason_ref": "insufficient-evidence",
    }


def _invocation() -> dict[str, object]:
    observed = _observed()
    abstained = _abstained()
    return {
        "contract_id": GOVERNED_RATER_OBSERVATION_CONTRACT_V1,
        "invocation_ref": "invocation-1",
        "configuration": _configuration(),
        "task_revision_ref": "task-v1",
        "rubric_revision_ref": "rubric-v1",
        "response_evidence_ref": "response-evidence-1",
        "observations": {
            observed.pop("criterion_ref"): observed,
            abstained.pop("criterion_ref"): abstained,
        },
    }


def _error_code(callable_object) -> str:
    with pytest.raises(RaterObservationError) as exc_info:
        callable_object()
    return exc_info.value.code


class _OversizedList(list[object]):
    """List whose contents must not be traversed after its size is rejected."""

    def __iter__(self):
        raise AssertionError("oversized input was traversed")


def test_round_trip_preserves_observations_without_decision_fields() -> None:
    invocation = RaterInvocation.from_mapping(_invocation())
    payload = invocation.to_payload()

    assert payload == _invocation()
    assert invocation.observations[0].category_anchor_ref == "category-2"
    assert invocation.observations[1].reason_ref == "insufficient-evidence"
    assert not {
        "score",
        "final_score",
        "latent_trait",
        "level",
        "placement",
        "pass_fail",
        "certification",
        "employment_decision",
    }.intersection(payload)


def test_top_level_score_or_decision_fields_are_rejected_explicitly() -> None:
    for field_name in ("score", "placement", "employment_decision"):
        payload = _invocation()
        payload[field_name] = "forbidden"
        assert _error_code(
            lambda payload=payload: RaterInvocation.from_mapping(payload)
        ) == ("decision_leakage")


def test_unknown_and_missing_top_level_fields_fail_closed() -> None:
    unknown = _invocation()
    unknown["provider_payload"] = {}
    assert _error_code(lambda: RaterInvocation.from_mapping(unknown)) == "unknown_field"

    missing = _invocation()
    del missing["rubric_revision_ref"]
    assert _error_code(lambda: RaterInvocation.from_mapping(missing)) == "missing_field"

    assert _error_code(lambda: RaterInvocation.from_mapping([])) == "invalid_object"
    assert _error_code(lambda: RaterInvocation.from_mapping({1: "value"})) == (
        "invalid_object_key"
    )


def test_configuration_requires_exact_fields_and_bounded_references() -> None:
    assert (
        RaterConfigurationIdentity.from_mapping(_configuration()).provider_ref
        == "provider"
    )

    unknown = _configuration()
    unknown["temperature"] = "1"
    assert _error_code(lambda: RaterConfigurationIdentity.from_mapping(unknown)) == (
        "unknown_field"
    )

    decision = _configuration()
    decision["score"] = "forbidden"
    assert _error_code(lambda: RaterConfigurationIdentity.from_mapping(decision)) == (
        "decision_leakage"
    )

    missing = _configuration()
    del missing["provider_ref"]
    assert _error_code(lambda: RaterConfigurationIdentity.from_mapping(missing)) == (
        "missing_field"
    )

    wrong_type = _configuration()
    wrong_type["provider_ref"] = 3  # type: ignore[assignment]
    assert _error_code(lambda: RaterConfigurationIdentity.from_mapping(wrong_type)) == (
        "invalid_reference"
    )

    empty = _configuration()
    empty["provider_ref"] = "   "
    assert _error_code(lambda: RaterConfigurationIdentity.from_mapping(empty)) == (
        "invalid_reference"
    )

    oversized = _configuration()
    oversized["provider_ref"] = "x" * (MAX_RATER_REFERENCE_LENGTH + 1)
    assert _error_code(lambda: RaterConfigurationIdentity.from_mapping(oversized)) == (
        "invalid_reference"
    )

    control = _configuration()
    control["provider_ref"] = "bad\nvalue"
    assert _error_code(lambda: RaterConfigurationIdentity.from_mapping(control)) == (
        "invalid_reference"
    )


def test_shared_canonical_reference_conformance_fixture() -> None:
    fixture_path = Path(__file__).parent / "fixtures/governed_rater_observation_v1_conformance.json"
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes)
    assert fixture["contract_id"] == GOVERNED_RATER_OBSERVATION_CONTRACT_V1
    assert GOVERNED_RATER_UPSTREAM_REVISION == "38487df3f5f84b475e07b39cf13c893293e542e7"
    assert GOVERNED_RATER_SCHEMA_SHA256 == "7d112c652523ca55546eea1114ecb9fd82727d77fc27434f2ee0ab2acd11d281"
    assert GOVERNED_RATER_CONFORMANCE_SHA256 == "c7c6c1a84d6f3073fa14ef0e65d409e5f35412b8667c9f2b759a30dc91d0024c"
    assert fixture["reference_cases"]
    for case in fixture["reference_cases"]:
        configuration = _configuration()
        configuration["provider_ref"] = case["value"]
        if case["valid"]:
            assert RaterConfigurationIdentity.from_mapping(configuration).provider_ref == case["value"]
        else:
            assert _error_code(lambda: RaterConfigurationIdentity.from_mapping(configuration)) == "invalid_reference"


def test_shared_duplicate_member_cases_fail_before_mapping_validation() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/governed_rater_observation_v1_conformance.json").read_text()
    )
    for case in fixture["observation_identity_cases"]:
        if case["valid"]:
            continue
        observations = case["json_text"]
        raw = json.dumps(_invocation()).replace(
            json.dumps(_invocation()["observations"]), observations
        )
        assert _error_code(lambda raw=raw: RaterInvocation.from_json(raw)) == "duplicate_object_member"


def test_observation_schema_is_exact_and_status_is_bounded() -> None:
    unknown = _observed()
    unknown["model_reasoning"] = "hidden"
    assert _error_code(lambda: CriterionObservation.from_mapping(unknown)) == (
        "unknown_field"
    )

    decision = _observed()
    decision["final_score"] = 7
    assert _error_code(lambda: CriterionObservation.from_mapping(decision)) == (
        "decision_leakage"
    )

    missing = _observed()
    del missing["uncertainty"]
    assert _error_code(lambda: CriterionObservation.from_mapping(missing)) == (
        "missing_field"
    )

    invalid_status = _observed()
    invalid_status["status"] = "failed"
    assert _error_code(lambda: CriterionObservation.from_mapping(invalid_status)) == (
        "invalid_status"
    )

    invalid_uncertainty = _observed()
    invalid_uncertainty["uncertainty"] = "certain"
    assert _error_code(
        lambda: CriterionObservation.from_mapping(invalid_uncertainty)
    ) == ("invalid_uncertainty")

    for invalid_value in ([], {}):
        invalid_status = _observed()
        invalid_status["status"] = invalid_value
        assert _error_code(
            lambda: CriterionObservation.from_mapping(invalid_status)
        ) == ("invalid_status")

        invalid_uncertainty = _observed()
        invalid_uncertainty["uncertainty"] = invalid_value
        assert (
            _error_code(lambda: CriterionObservation.from_mapping(invalid_uncertainty))
            == "invalid_uncertainty"
        )

    assert (
        _error_code(lambda: CriterionObservation.from_mapping([])) == "invalid_object"
    )


def test_observed_state_requires_unique_bounded_evidence_and_no_reason() -> None:
    no_evidence = _observed()
    no_evidence["evidence_reference_ids"] = []
    assert _error_code(lambda: CriterionObservation.from_mapping(no_evidence)) == (
        "invalid_references"
    )

    duplicate_evidence = _observed()
    duplicate_evidence["evidence_reference_ids"] = ["same", "same"]
    assert _error_code(
        lambda: CriterionObservation.from_mapping(duplicate_evidence)
    ) == ("duplicate_reference")

    bad_evidence_type = _observed()
    bad_evidence_type["evidence_reference_ids"] = "not-an-array"
    assert _error_code(
        lambda: CriterionObservation.from_mapping(bad_evidence_type)
    ) == ("invalid_references")

    oversized_evidence = _observed()
    oversized_evidence["evidence_reference_ids"] = [
        f"evidence-{index}" for index in range(MAX_RATER_EVIDENCE_REFERENCES + 1)
    ]
    assert _error_code(
        lambda: CriterionObservation.from_mapping(oversized_evidence)
    ) == ("invalid_references")

    reason = _observed()
    reason["reason_ref"] = "should-not-exist"
    assert _error_code(lambda: CriterionObservation.from_mapping(reason)) == (
        "invalid_observed_state"
    )


def test_abstention_has_reason_but_no_category_or_evidence() -> None:
    assert CriterionObservation.from_mapping(_abstained()).status == "abstained"

    category = _abstained()
    category["category_anchor_ref"] = "category-1"
    assert _error_code(lambda: CriterionObservation.from_mapping(category)) == (
        "invalid_abstention_state"
    )

    evidence = _abstained()
    evidence["evidence_reference_ids"] = ["evidence"]
    assert _error_code(lambda: CriterionObservation.from_mapping(evidence)) == (
        "invalid_abstention_state"
    )

    missing_reason = _abstained()
    missing_reason["reason_ref"] = None
    assert _error_code(lambda: CriterionObservation.from_mapping(missing_reason)) == (
        "invalid_reference"
    )

    duplicate_signals = _abstained()
    duplicate_signals["review_signal_refs"] = ["review", "review"]
    assert _error_code(
        lambda: CriterionObservation.from_mapping(duplicate_signals)
    ) == ("duplicate_reference")

    wrong_signal_type = _abstained()
    wrong_signal_type["review_signal_refs"] = "review"
    assert _error_code(
        lambda: CriterionObservation.from_mapping(wrong_signal_type)
    ) == ("invalid_references")

    oversized_signals = _abstained()
    oversized_signals["review_signal_refs"] = [
        f"signal-{index}" for index in range(MAX_RATER_REVIEW_SIGNALS + 1)
    ]
    assert _error_code(
        lambda: CriterionObservation.from_mapping(oversized_signals)
    ) == ("invalid_references")


def test_invocation_aggregate_enforces_contract_and_criterion_uniqueness() -> None:
    incompatible = _invocation()
    incompatible["contract_id"] = "other/v1"
    assert _error_code(lambda: RaterInvocation.from_mapping(incompatible)) == (
        "contract_incompatible"
    )

    empty = _invocation()
    empty["observations"] = {}
    assert _error_code(lambda: RaterInvocation.from_mapping(empty)) == (
        "invalid_observations"
    )

    oversized = _invocation()
    oversized["observations"] = {
        f"criterion-{index}": _observed()
        for index in range(MAX_RATER_OBSERVATIONS + 1)
    }
    assert _error_code(lambda: RaterInvocation.from_mapping(oversized)) == (
        "invalid_observations"
    )

    wrong_container = _invocation()
    wrong_container["observations"] = "observation"
    assert _error_code(lambda: RaterInvocation.from_mapping(wrong_container)) == (
        "invalid_object"
    )


def test_collection_limits_are_checked_before_untrusted_values_are_traversed() -> None:
    invocation = _invocation()
    invocation["observations"] = {
        f"criterion-{index}": None for index in range(MAX_RATER_OBSERVATIONS + 1)
    }
    assert _error_code(lambda: RaterInvocation.from_mapping(invocation)) == (
        "invalid_observations"
    )

    oversized_evidence = _observed()
    oversized_evidence["evidence_reference_ids"] = _OversizedList(
        [None] * (MAX_RATER_EVIDENCE_REFERENCES + 1)
    )
    assert _error_code(
        lambda: CriterionObservation.from_mapping(oversized_evidence)
    ) == ("invalid_references")

    oversized_signals = _abstained()
    oversized_signals["review_signal_refs"] = _OversizedList(
        [None] * (MAX_RATER_REVIEW_SIGNALS + 1)
    )
    assert _error_code(
        lambda: CriterionObservation.from_mapping(oversized_signals)
    ) == ("invalid_references")

    wrong_observation = _invocation()
    wrong_observation["observations"] = {"criterion": "observation"}
    assert _error_code(lambda: RaterInvocation.from_mapping(wrong_observation)) == (
        "invalid_object"
    )

    wrong_configuration = _invocation()
    wrong_configuration["configuration"] = []
    assert _error_code(lambda: RaterInvocation.from_mapping(wrong_configuration)) == (
        "invalid_object"
    )


def test_direct_domain_construction_rejects_wrong_types() -> None:
    configuration = RaterConfigurationIdentity.from_mapping(_configuration())
    observation = CriterionObservation.from_mapping(_observed())

    assert (
        _error_code(
            lambda: RaterInvocation(
                invocation_ref="invocation",
                configuration="wrong",  # type: ignore[arg-type]
                task_revision_ref="task",
                rubric_revision_ref="rubric",
                response_evidence_ref="response",
                observations=(observation,),
            )
        )
        == "invalid_configuration"
    )

    assert (
        _error_code(
            lambda: RaterInvocation(
                invocation_ref="invocation",
                configuration=configuration,
                task_revision_ref="task",
                rubric_revision_ref="rubric",
                response_evidence_ref="response",
                observations=("wrong",),  # type: ignore[arg-type]
            )
        )
        == "invalid_observation"
    )


def test_mapping_inputs_are_snapshotted_into_immutable_domain_values() -> None:
    payload = _invocation()
    original = deepcopy(payload)
    invocation = RaterInvocation.from_mapping(payload)

    payload["configuration"]["provider_ref"] = "mutated"  # type: ignore[index]
    payload["observations"]["criterion-a"]["evidence_reference_ids"].append("mutated")  # type: ignore[index,union-attr]

    assert invocation.to_payload() == original
