"""Contracts for criterion-bound governed rater observations."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from contextual_orchestrator.evaluation_criterion_binding import (
    CategoryExecutionBinding,
    CriterionExecutionBinding,
    CriterionSetExecutionBinding,
    EvaluationCriterionBindingError,
)
from contextual_orchestrator.rater_observation import (
    GOVERNED_RATER_OBSERVATION_CONTRACT_V1,
    MAX_RATER_EVIDENCE_REFERENCES,
    MAX_RATER_OBSERVATIONS,
    MAX_RATER_REVIEW_SIGNALS,
    CriterionObservation,
    RaterConfigurationIdentity,
    RaterInvocation,
    RaterObservationError,
)


def _category(seed: str, order: int) -> dict[str, object]:
    """Return one category definition receipt."""
    return {
        "definition_ref": f"{seed}_definition",
        "definition_sha256": seed[0] * 64,
        "order_index": order,
    }


def _criterion(seed: str) -> dict[str, object]:
    """Return one substantive criterion receipt."""
    return {
        "criterion_revision_ref": f"{seed}_revision_1",
        "definition_ref": f"{seed}_definition",
        "definition_sha256": "1" * 64,
        "admissible_evidence_rule_ref": f"{seed}_evidence_rule",
        "admissible_evidence_rule_sha256": "2" * 64,
        "exclusion_rule_ref": f"{seed}_exclusion_rule",
        "exclusion_rule_sha256": "3" * 64,
        "response_semantics_ref": f"{seed}_response_semantics",
        "response_semantics_sha256": "4" * 64,
        "abstention_rule_ref": f"{seed}_abstention_rule",
        "abstention_rule_sha256": "5" * 64,
        "not_observable_rule_ref": f"{seed}_not_observable_rule",
        "not_observable_rule_sha256": "6" * 64,
        "categories": {
            f"{seed}_not_supported": _category("a_category", 0),
            f"{seed}_supported": _category("b_category", 1),
        },
    }


def _criterion_set() -> dict[str, object]:
    """Return an immutable non-empty criterion set."""
    return {
        "criterion_set_snapshot_ref": "criterion_set_snapshot_1",
        "criterion_set_sha256": "a" * 64,
        "blueprint_revision_ref": "evaluation_blueprint_revision_1",
        "rubric_revision_ref": "rubric_revision_1",
        "intended_use_ref": "intended_use_1",
        "construct_ref": "construct_1",
        "population_scope_ref": "population_scope_1",
        "language_scope_ref": "language_scope_1",
        "domain_scope_ref": "domain_scope_1",
        "criteria": {
            "criterion_evidence_support": _criterion(
                "criterion_evidence_support"
            ),
            "criterion_safety": _criterion("criterion_safety"),
        },
    }


def _configuration() -> dict[str, str]:
    """Return one exact rater configuration."""
    return {
        "rater_family_ref": "rater-family",
        "provider_ref": "provider",
        "implementation_revision_ref": "implementation-v1",
        "instruction_revision_ref": "instruction-v1",
        "response_schema_revision_ref": "schema-v1",
        "workflow_mode_ref": "independent-blind",
        "modality_channel_ref": "text",
    }


def _observed(category: str = "criterion_evidence_support_supported") -> dict[str, Any]:
    """Return one observed criterion payload."""
    return {
        "status": "observed",
        "category_anchor_ref": category,
        "evidence_reference_ids": ["evidence-1"],
        "uncertainty": "low",
        "review_signal_refs": [],
        "reason_ref": None,
    }


def _abstained() -> dict[str, Any]:
    """Return one explicit abstention payload."""
    return {
        "status": "abstained",
        "category_anchor_ref": None,
        "evidence_reference_ids": [],
        "uncertainty": "high",
        "review_signal_refs": ["review-1"],
        "reason_ref": "insufficient-evidence",
    }


def _invocation() -> dict[str, Any]:
    """Return one complete criterion-bound invocation."""
    return {
        "contract_id": GOVERNED_RATER_OBSERVATION_CONTRACT_V1,
        "invocation_ref": "invocation-1",
        "configuration": _configuration(),
        "evaluation_run_snapshot_ref": "run-snapshot-1",
        "item_instance_ref": "item-instance-1",
        "task_revision_ref": "task-v1",
        "rubric_revision_ref": "rubric_revision_1",
        "criterion_set": _criterion_set(),
        "response_evidence_ref": "response-evidence-1",
        "observations": {
            "criterion_evidence_support": _observed(),
            "criterion_safety": _abstained(),
        },
    }


def _code(callable_: Any) -> str:
    """Return a stable domain error code from one failing call."""
    with pytest.raises((RaterObservationError, EvaluationCriterionBindingError)) as err:
        callable_()
    return err.value.code


def test_criterion_set_carries_substantive_rules_categories_and_scope() -> None:
    """Criterion meaning is explicit and content-addressed before evaluation."""
    binding = CriterionSetExecutionBinding.from_mapping(_criterion_set())
    criterion = binding.criterion("criterion_evidence_support")
    assert criterion.definition_ref == "criterion_evidence_support_definition"
    assert criterion.admissible_evidence_rule_ref.endswith("_evidence_rule")
    assert criterion.exclusion_rule_ref.endswith("_exclusion_rule")
    assert criterion.response_semantics_ref.endswith("_response_semantics")
    assert criterion.abstention_rule_ref.endswith("_abstention_rule")
    assert criterion.not_observable_rule_ref.endswith("_not_observable_rule")
    assert criterion.category_refs == (
        "criterion_evidence_support_not_supported",
        "criterion_evidence_support_supported",
    )
    assert binding.intended_use_ref == "intended_use_1"
    assert binding.to_payload() == _criterion_set()


def test_criterion_set_rejects_missing_empty_unknown_and_malformed_meaning() -> None:
    """Refs alone cannot stand in for missing criterion rules or categories."""
    empty = _criterion_set()
    empty["criteria"] = {}
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(empty)) == (
        "invalid_criterion_set"
    )

    missing = _criterion_set()
    del missing["construct_ref"]
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(missing)) == (
        "missing_field"
    )

    unknown = _criterion_set()
    unknown["score"] = 1
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(unknown)) == (
        "unknown_field"
    )

    malformed = _criterion_set()
    malformed["criterion_set_sha256"] = "bad"
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(malformed)) == (
        "invalid_sha256"
    )

    wrong = _criterion_set()
    wrong["criteria"] = []
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(wrong)) == (
        "invalid_object"
    )

    non_string = _criterion_set()
    non_string["criteria"] = {1: _criterion("criterion")}
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(non_string)) == (
        "invalid_object_key"
    )


def test_criterion_categories_are_defined_unique_ordered_and_bounded() -> None:
    """Every observed category has content-addressed meaning and stable order."""
    payload = _criterion("criterion")
    payload["categories"] = {"only": _category("a_category", 0)}
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(
            payload, criterion_ref="criterion"
        )
    ) == "invalid_category_set"

    payload = _criterion("criterion")
    categories = dict(payload["categories"])
    categories["third"] = _category("c_category", 1)
    payload["categories"] = categories
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(
            payload, criterion_ref="criterion"
        )
    ) == "duplicate_order_index"

    payload = _criterion("criterion")
    categories = dict(payload["categories"])
    categories["criterion_supported"]["order_index"] = 3
    payload["categories"] = categories
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(
            payload, criterion_ref="criterion"
        )
    ) == "non_contiguous_order_index"

    assert _code(
        lambda: CategoryExecutionBinding.from_mapping(
            {"definition_ref": "x", "definition_sha256": "a" * 64},
            category_ref="category",
        )
    ) == "missing_field"


def test_criterion_binding_rejects_unsafe_types_references_and_indexes() -> None:
    """Transport aliases and invalid category indexes fail closed."""
    payload = _criterion("criterion")
    payload["definition_ref"] = " criterion"
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(
            payload, criterion_ref="criterion"
        )
    ) == "invalid_reference"

    payload = _criterion("criterion")
    payload["definition_sha256"] = object()
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(
            payload, criterion_ref="criterion"
        )
    ) == "invalid_sha256"

    assert _code(
        lambda: CategoryExecutionBinding.from_mapping(
            {
                "definition_ref": "definition",
                "definition_sha256": "a" * 64,
                "order_index": True,
            },
            category_ref="category",
        )
    ) == "invalid_order_index"

    binding = CriterionSetExecutionBinding.from_mapping(_criterion_set())
    assert _code(lambda: binding.criterion("not-registered")) == (
        "criterion_not_registered"
    )


def test_rater_invocation_round_trip_requires_exact_run_item_and_criterion_set() -> None:
    """A provider result cannot exist without the evaluated criterion meaning."""
    payload = _invocation()
    invocation = RaterInvocation.from_mapping(payload)
    assert invocation.to_payload() == payload
    assert invocation.evaluation_run_snapshot_ref == "run-snapshot-1"
    assert invocation.item_instance_ref == "item-instance-1"

    for field in (
        "evaluation_run_snapshot_ref",
        "item_instance_ref",
        "criterion_set",
    ):
        missing = _invocation()
        del missing[field]
        assert _code(lambda missing=missing: RaterInvocation.from_mapping(missing)) == (
            "missing_field"
        )


def test_invocation_rejects_missing_extra_or_duplicate_criteria() -> None:
    """Every declared criterion is observed or explicitly abstained exactly once."""
    missing = _invocation()
    missing["observations"].pop("criterion_safety")
    assert _code(lambda: RaterInvocation.from_mapping(missing)) == (
        "criterion_coverage_mismatch"
    )

    extra = _invocation()
    extra["observations"]["criterion_invented"] = _abstained()
    assert _code(lambda: RaterInvocation.from_mapping(extra)) == (
        "criterion_coverage_mismatch"
    )

    configuration = RaterConfigurationIdentity.from_mapping(_configuration())
    binding = CriterionSetExecutionBinding.from_mapping(_criterion_set())
    duplicate = CriterionObservation.from_mapping(
        _observed(), criterion_ref="criterion_evidence_support"
    )
    assert _code(
        lambda: RaterInvocation(
            invocation_ref="invocation",
            configuration=configuration,
            evaluation_run_snapshot_ref="run",
            item_instance_ref="item",
            task_revision_ref="task",
            rubric_revision_ref="rubric_revision_1",
            criterion_set=binding,
            response_evidence_ref="response",
            observations=(duplicate, duplicate),
        )
    ) == "duplicate_criterion"


def test_invocation_rejects_category_and_rubric_substitution() -> None:
    """A result cannot borrow a category or rubric from another criterion set."""
    category = _invocation()
    category["observations"]["criterion_evidence_support"] = _observed(
        "criterion_safety_supported"
    )
    assert _code(lambda: RaterInvocation.from_mapping(category)) == (
        "category_not_admitted"
    )

    rubric = _invocation()
    rubric["rubric_revision_ref"] = "rubric_revision_2"
    assert _code(lambda: RaterInvocation.from_mapping(rubric)) == (
        "criterion_set_rubric_mismatch"
    )


def test_invocation_json_rejects_duplicate_members_depth_and_invalid_json() -> None:
    """Raw provider JSON cannot exploit duplicate-member or nesting ambiguity."""
    payload = _invocation()
    parsed = RaterInvocation.from_json(json.dumps(payload))
    assert parsed.to_payload() == payload

    duplicate = '{"contract_id":"a","contract_id":"b"}'
    assert _code(lambda: RaterInvocation.from_json(duplicate)) == (
        "duplicate_object_member"
    )

    nested = "[" * 65 + "0" + "]" * 65
    assert _code(lambda: RaterInvocation.from_json(nested)) == "invalid_json"
    assert _code(lambda: RaterInvocation.from_json("{")) == "invalid_json"
    assert _code(lambda: RaterInvocation.from_json(object())) == "invalid_json"


def test_observed_and_abstained_states_preserve_evidence_semantics() -> None:
    """Observed evidence and abstention reasons remain mutually exclusive."""
    observed = CriterionObservation.from_mapping(_observed(), criterion_ref="criterion")
    assert observed.to_payload() == _observed()
    abstained = CriterionObservation.from_mapping(
        _abstained(), criterion_ref="criterion"
    )
    assert abstained.to_payload() == _abstained()

    no_evidence = _observed()
    no_evidence["evidence_reference_ids"] = []
    assert _code(
        lambda: CriterionObservation.from_mapping(
            no_evidence, criterion_ref="criterion"
        )
    ) == "invalid_references"

    with_reason = _observed()
    with_reason["reason_ref"] = "reason"
    assert _code(
        lambda: CriterionObservation.from_mapping(
            with_reason, criterion_ref="criterion"
        )
    ) == "invalid_observed_state"

    with_category = _abstained()
    with_category["category_anchor_ref"] = "category"
    assert _code(
        lambda: CriterionObservation.from_mapping(
            with_category, criterion_ref="criterion"
        )
    ) == "invalid_abstention_state"

    no_reason = _abstained()
    no_reason["reason_ref"] = None
    assert _code(
        lambda: CriterionObservation.from_mapping(
            no_reason, criterion_ref="criterion"
        )
    ) == "invalid_reference"


def test_reference_and_collection_boundaries_fail_closed() -> None:
    """References, evidence, review signals, and observations remain bounded."""
    for value in ("", " ref", "ref ", "\ufeffref", "ref\ufeff", "a\nb", "\ud800"):
        assert _code(
            lambda value=value: CriterionObservation.from_mapping(
                {**_observed(), "criterion_ref": value}
            )
        ) == "invalid_reference"

    evidence = _observed()
    evidence["evidence_reference_ids"] = [
        f"evidence-{index}" for index in range(MAX_RATER_EVIDENCE_REFERENCES + 1)
    ]
    assert _code(
        lambda: CriterionObservation.from_mapping(evidence, criterion_ref="criterion")
    ) == "invalid_references"

    signals = _abstained()
    signals["review_signal_refs"] = [
        f"signal-{index}" for index in range(MAX_RATER_REVIEW_SIGNALS + 1)
    ]
    assert _code(
        lambda: CriterionObservation.from_mapping(signals, criterion_ref="criterion")
    ) == "invalid_references"

    empty = _invocation()
    empty["observations"] = {}
    assert _code(lambda: RaterInvocation.from_mapping(empty)) == (
        "invalid_observations"
    )

    oversized = _invocation()
    oversized["observations"] = {
        f"criterion-{index}": _observed()
        for index in range(MAX_RATER_OBSERVATIONS + 1)
    }
    assert _code(lambda: RaterInvocation.from_mapping(oversized)) == (
        "invalid_observations"
    )


def test_configuration_and_acl_reject_unknown_decision_and_wrong_types() -> None:
    """Only closed provider-neutral configuration and observation fields pass."""
    config = _configuration()
    config["unknown"] = "x"
    assert _code(lambda: RaterConfigurationIdentity.from_mapping(config)) == (
        "unknown_field"
    )

    decision = _invocation()
    decision["score"] = 1
    assert _code(lambda: RaterInvocation.from_mapping(decision)) == (
        "decision_leakage"
    )

    wrong = _invocation()
    wrong["configuration"] = []
    assert _code(lambda: RaterInvocation.from_mapping(wrong)) == "invalid_object"

    configuration = RaterConfigurationIdentity.from_mapping(_configuration())
    binding = CriterionSetExecutionBinding.from_mapping(_criterion_set())
    observation = CriterionObservation.from_mapping(
        _observed(), criterion_ref="criterion_evidence_support"
    )
    assert _code(
        lambda: RaterInvocation(
            invocation_ref="invocation",
            configuration=object(),
            evaluation_run_snapshot_ref="run",
            item_instance_ref="item",
            task_revision_ref="task",
            rubric_revision_ref="rubric_revision_1",
            criterion_set=binding,
            response_evidence_ref="response",
            observations=(observation,),
        )
    ) == "invalid_configuration"
    assert _code(
        lambda: RaterInvocation(
            invocation_ref="invocation",
            configuration=configuration,
            evaluation_run_snapshot_ref="run",
            item_instance_ref="item",
            task_revision_ref="task",
            rubric_revision_ref="rubric_revision_1",
            criterion_set=object(),
            response_evidence_ref="response",
            observations=(observation,),
        )
    ) == "invalid_criterion_set"


def test_mapping_inputs_are_detached_from_caller_mutation() -> None:
    """The invocation keeps the exact criterion and observation snapshot."""
    payload = _invocation()
    expected = deepcopy(payload)
    invocation = RaterInvocation.from_mapping(payload)
    payload["criterion_set"]["criteria"]["criterion_safety"]["definition_ref"] = (
        "mutated"
    )
    payload["observations"]["criterion_evidence_support"][
        "evidence_reference_ids"
    ].append("mutated")
    assert invocation.to_payload() == expected
