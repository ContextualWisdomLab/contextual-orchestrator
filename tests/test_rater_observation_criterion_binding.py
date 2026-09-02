"""Focused criterion-set binding regressions for governed rater output."""

from __future__ import annotations

import pytest

from contextual_orchestrator.evaluation_criterion_binding import (
    CriterionSetExecutionBinding,
)
from contextual_orchestrator.rater_observation import (
    GOVERNED_RATER_OBSERVATION_CONTRACT_V1,
    RaterInvocation,
    RaterObservationError,
)


def _criterion(category_prefix: str) -> dict[str, object]:
    """Return a two-category content-addressed criterion."""
    return {
        "criterion_revision_ref": f"{category_prefix}_revision_1",
        "definition_ref": f"{category_prefix}_definition",
        "definition_sha256": "1" * 64,
        "admissible_evidence_rule_ref": f"{category_prefix}_evidence_rule",
        "admissible_evidence_rule_sha256": "2" * 64,
        "exclusion_rule_ref": f"{category_prefix}_exclusion_rule",
        "exclusion_rule_sha256": "3" * 64,
        "response_semantics_ref": f"{category_prefix}_response_semantics",
        "response_semantics_sha256": "4" * 64,
        "abstention_rule_ref": f"{category_prefix}_abstention_rule",
        "abstention_rule_sha256": "5" * 64,
        "not_observable_rule_ref": f"{category_prefix}_not_observable_rule",
        "not_observable_rule_sha256": "6" * 64,
        "categories": {
            f"{category_prefix}_not_supported": {
                "definition_ref": f"{category_prefix}_not_supported_definition",
                "definition_sha256": "7" * 64,
                "order_index": 0,
            },
            f"{category_prefix}_supported": {
                "definition_ref": f"{category_prefix}_supported_definition",
                "definition_sha256": "8" * 64,
                "order_index": 1,
            },
        },
    }


def _criterion_set_payload() -> dict[str, object]:
    """Return one immutable substantive criterion-set binding."""
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


def _invocation_payload() -> dict[str, object]:
    """Return one complete provider-neutral rater invocation."""
    return {
        "contract_id": GOVERNED_RATER_OBSERVATION_CONTRACT_V1,
        "invocation_ref": "rater_invocation_1",
        "configuration": {
            "rater_family_ref": "rater_family_1",
            "provider_ref": "provider_1",
            "implementation_revision_ref": "implementation_revision_1",
            "instruction_revision_ref": "instruction_revision_1",
            "response_schema_revision_ref": "response_schema_revision_1",
            "workflow_mode_ref": "workflow_mode_1",
            "modality_channel_ref": "modality_text_1",
        },
        "evaluation_run_snapshot_ref": "evaluation_run_snapshot_1",
        "item_instance_ref": "evaluation_item_1",
        "task_revision_ref": "task_revision_1",
        "rubric_revision_ref": "rubric_revision_1",
        "criterion_set": _criterion_set_payload(),
        "response_evidence_ref": "response_evidence_1",
        "observations": {
            "criterion_evidence_support": {
                "status": "observed",
                "category_anchor_ref": "criterion_evidence_support_supported",
                "evidence_reference_ids": ["evidence_1"],
                "uncertainty": "low",
                "review_signal_refs": [],
                "reason_ref": None,
            },
            "criterion_safety": {
                "status": "abstained",
                "category_anchor_ref": None,
                "evidence_reference_ids": [],
                "uncertainty": "high",
                "review_signal_refs": ["review_signal_1"],
                "reason_ref": "insufficient_evidence_1",
            },
        },
    }


def test_exact_substantive_criterion_set_is_carried_with_the_invocation() -> None:
    """The result identifies the exact criteria, rules, categories, and scope."""
    invocation = RaterInvocation.from_mapping(_invocation_payload())
    binding = invocation.criterion_set
    assert binding.criterion_set_snapshot_ref == "criterion_set_snapshot_1"
    assert binding.criterion("criterion_safety").response_semantics_ref == (
        "criterion_safety_response_semantics"
    )
    assert invocation.to_payload()["criterion_set"] == _criterion_set_payload()


def test_unbound_or_partially_defined_criteria_are_rejected() -> None:
    """No observation may be emitted from names-only criterion references."""
    missing = _invocation_payload()
    del missing["criterion_set"]
    with pytest.raises(RaterObservationError) as caught:
        RaterInvocation.from_mapping(missing)
    assert caught.value.code == "missing_field"

    partial = _criterion_set_payload()
    criterion = dict(partial["criteria"]["criterion_safety"])
    del criterion["admissible_evidence_rule_ref"]
    partial["criteria"]["criterion_safety"] = criterion
    payload = _invocation_payload()
    payload["criterion_set"] = partial
    with pytest.raises(RaterObservationError) as caught:
        RaterInvocation.from_mapping(payload)
    assert caught.value.code == "missing_field"


def test_coverage_category_and_rubric_substitution_fail_closed() -> None:
    """The provider cannot omit criteria, invent categories, or swap rubrics."""
    missing = _invocation_payload()
    missing["observations"].pop("criterion_safety")
    with pytest.raises(RaterObservationError) as caught:
        RaterInvocation.from_mapping(missing)
    assert caught.value.code == "criterion_coverage_mismatch"

    category = _invocation_payload()
    category["observations"]["criterion_evidence_support"][
        "category_anchor_ref"
    ] = "criterion_safety_supported"
    with pytest.raises(RaterObservationError) as caught:
        RaterInvocation.from_mapping(category)
    assert caught.value.code == "category_not_admitted"

    rubric = _invocation_payload()
    rubric["rubric_revision_ref"] = "rubric_revision_2"
    with pytest.raises(RaterObservationError) as caught:
        RaterInvocation.from_mapping(rubric)
    assert caught.value.code == "criterion_set_rubric_mismatch"


def test_criterion_set_is_nonempty_and_content_addressed() -> None:
    """Cold-start item banks may have no anchors, never no criteria."""
    binding = CriterionSetExecutionBinding.from_mapping(_criterion_set_payload())
    assert binding.criterion_refs == (
        "criterion_evidence_support",
        "criterion_safety",
    )
    assert binding.criterion_set_sha256 == "a" * 64
