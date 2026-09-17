"""Focused trusted-criterion regressions for governed rater output."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

from contextual_orchestrator.evaluation_criterion_binding import (
    CriterionSetExecutionBinding,
    EvaluationCriterionBindingError,
)
from contextual_orchestrator.rater_observation import (
    GOVERNED_RATER_OBSERVATION_CONTRACT_V1,
    RaterInvocation,
    RaterObservationError,
)


def _digest(payload: dict[str, Any]) -> str:
    """Return the canonical digest of criterion-set content."""
    content = deepcopy(payload)
    content.pop("criterion_set_sha256", None)
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _criterion(prefix: str) -> dict[str, Any]:
    """Return one complete content-addressed criterion."""
    return {
        "criterion_revision_ref": f"{prefix}_revision_1",
        "definition_ref": f"{prefix}_definition",
        "definition_sha256": "1" * 64,
        "admissible_evidence_rule_ref": f"{prefix}_evidence_rule",
        "admissible_evidence_rule_sha256": "2" * 64,
        "exclusion_rule_ref": f"{prefix}_exclusion_rule",
        "exclusion_rule_sha256": "3" * 64,
        "response_semantics_ref": f"{prefix}_response_semantics",
        "response_semantics_sha256": "4" * 64,
        "abstention_rule_ref": f"{prefix}_abstention_rule",
        "abstention_rule_sha256": "5" * 64,
        "not_observable_rule_ref": f"{prefix}_not_observable_rule",
        "not_observable_rule_sha256": "6" * 64,
        "categories": {
            f"{prefix}_not_supported": {
                "definition_ref": f"{prefix}_not_supported_definition",
                "definition_sha256": "7" * 64,
                "order_index": 0,
            },
            f"{prefix}_supported": {
                "definition_ref": f"{prefix}_supported_definition",
                "definition_sha256": "8" * 64,
                "order_index": 1,
            },
        },
    }


def _criterion_set(*, construct: str = "construct_1") -> dict[str, Any]:
    """Return one immutable substantive criterion-set binding."""
    payload: dict[str, Any] = {
        "criterion_set_snapshot_ref": "criterion_set_snapshot_1",
        "criterion_set_sha256": "",
        "blueprint_revision_ref": "evaluation_blueprint_revision_1",
        "rubric_revision_ref": "rubric_revision_1",
        "intended_use_ref": "intended_use_1",
        "construct_ref": construct,
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
    payload["criterion_set_sha256"] = _digest(payload)
    return payload


def _invocation(criterion_set: dict[str, Any]) -> dict[str, Any]:
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
        "criterion_set": deepcopy(criterion_set),
        "response_evidence_ref": "response_evidence_1",
        "observations": {
            "criterion_evidence_support": {
                "status": "observed",
                "category_anchor_ref": (
                    "criterion_evidence_support_supported"
                ),
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


def _code(callable_: Any) -> str:
    """Return one stable boundary error code."""
    with pytest.raises(
        (EvaluationCriterionBindingError, RaterObservationError)
    ) as caught:
        callable_()
    return caught.value.code


def test_exact_substantive_criterion_set_is_carried_with_the_invocation() -> None:
    """The result identifies the exact criteria, rules, categories, and scope."""
    criterion_payload = _criterion_set()
    trusted = CriterionSetExecutionBinding.from_mapping(criterion_payload)
    invocation = RaterInvocation.from_mapping(
        _invocation(criterion_payload),
        expected_criterion_set=trusted,
    )
    assert invocation.criterion_set is trusted
    assert trusted.criterion_set_snapshot_ref == "criterion_set_snapshot_1"
    assert trusted.criterion("criterion_safety").response_semantics_ref == (
        "criterion_safety_response_semantics"
    )
    assert invocation.to_payload()["criterion_set"] == criterion_payload


def test_unbound_and_whole_substituted_criteria_are_rejected() -> None:
    """No provider can choose or replace the policy it claims to evaluate."""
    expected_payload = _criterion_set()
    trusted = CriterionSetExecutionBinding.from_mapping(expected_payload)

    assert _code(
        lambda: RaterInvocation.from_mapping(_invocation(expected_payload))
    ) == "trusted_criterion_set_required"

    substituted_payload = _criterion_set(construct="foreign_construct")
    assert _code(
        lambda: RaterInvocation.from_mapping(
            _invocation(substituted_payload),
            expected_criterion_set=trusted,
        )
    ) == "criterion_set_substitution"


def test_digest_and_coverage_substitution_fail_closed() -> None:
    """Stale criterion content and partial result coverage remain invalid."""
    expected_payload = _criterion_set()
    trusted = CriterionSetExecutionBinding.from_mapping(expected_payload)

    stale = _invocation(expected_payload)
    stale["criterion_set"]["criteria"]["criterion_safety"][
        "response_semantics_ref"
    ] = "changed_semantics"
    assert _code(
        lambda: RaterInvocation.from_mapping(
            stale,
            expected_criterion_set=trusted,
        )
    ) == "criterion_set_digest_mismatch"

    missing = _invocation(expected_payload)
    missing["observations"].pop("criterion_safety")
    assert _code(
        lambda: RaterInvocation.from_mapping(
            missing,
            expected_criterion_set=trusted,
        )
    ) == "criterion_coverage_mismatch"

    category = _invocation(expected_payload)
    category["observations"]["criterion_evidence_support"][
        "category_anchor_ref"
    ] = "criterion_safety_supported"
    assert _code(
        lambda: RaterInvocation.from_mapping(
            category,
            expected_criterion_set=trusted,
        )
    ) == "category_not_admitted"
