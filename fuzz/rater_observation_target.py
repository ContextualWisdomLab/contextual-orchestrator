"""Shared fuzz invariant for trusted criterion-bound rater observations."""

from __future__ import annotations

from typing import Any

from contextual_orchestrator.evaluation_criterion_binding import (
    CriterionSetExecutionBinding,
)
from contextual_orchestrator.rater_observation import (
    MAX_RATER_OBSERVATIONS,
    RaterInvocation,
    RaterObservationError,
)

_TRUSTED_CRITERION_PAYLOAD = {
    "criterion_set_snapshot_ref": "criterion-set",
    "criterion_set_sha256": (
        "22253b81f541cb77801000cfa724ed2aadb3cd0a34c0f9c0192d5e77476c507f"
    ),
    "blueprint_revision_ref": "blueprint",
    "rubric_revision_ref": "rubric",
    "intended_use_ref": "intended-use",
    "construct_ref": "construct",
    "population_scope_ref": "population",
    "language_scope_ref": "language",
    "domain_scope_ref": "domain",
    "criteria": {
        "c": {
            "criterion_revision_ref": "criterion-revision",
            "definition_ref": "criterion-definition",
            "definition_sha256": "1" * 64,
            "admissible_evidence_rule_ref": "evidence-rule",
            "admissible_evidence_rule_sha256": "2" * 64,
            "exclusion_rule_ref": "exclusion-rule",
            "exclusion_rule_sha256": "3" * 64,
            "response_semantics_ref": "response-semantics",
            "response_semantics_sha256": "4" * 64,
            "abstention_rule_ref": "abstention-rule",
            "abstention_rule_sha256": "5" * 64,
            "not_observable_rule_ref": "not-observable-rule",
            "not_observable_rule_sha256": "6" * 64,
            "categories": {
                "c-not-supported": {
                    "definition_ref": "category-zero",
                    "definition_sha256": "7" * 64,
                    "order_index": 0,
                },
                "c-supported": {
                    "definition_ref": "category-one",
                    "definition_sha256": "8" * 64,
                    "order_index": 1,
                },
            },
        }
    },
}
_TRUSTED_CRITERION_SET = CriterionSetExecutionBinding.from_mapping(
    _TRUSTED_CRITERION_PAYLOAD
)


def exercise_rater_observation(value: Any) -> None:
    """Fail closed or round-trip under one independently trusted criterion set."""
    try:
        invocation = RaterInvocation.from_mapping(
            value,
            expected_criterion_set=_TRUSTED_CRITERION_SET,
        )
    except RaterObservationError:
        return
    payload = invocation.to_payload()
    assert 1 <= len(payload["observations"]) <= MAX_RATER_OBSERVATIONS
    assert (
        RaterInvocation.from_mapping(
            payload,
            expected_criterion_set=_TRUSTED_CRITERION_SET,
        ).to_payload()
        == payload
    )
