"""Criterion-set binding contracts for governed rater observations."""

from __future__ import annotations

import pytest

from contextual_orchestrator.evaluation_criterion_binding import (
    CriterionExecutionBinding,
    CriterionSetExecutionBinding,
    EvaluationCriterionBindingError,
)
from contextual_orchestrator.rater_observation import (
    GOVERNED_RATER_OBSERVATION_CONTRACT_V1,
    RaterInvocation,
    RaterObservationError,
)


def _criterion_set_payload() -> dict[str, object]:
    """Return one immutable source-text-free criterion-set binding."""
    return {
        "criterion_set_snapshot_ref": "criterion_set_snapshot_1",
        "criterion_set_sha256": "a" * 64,
        "blueprint_revision_ref": "evaluation_blueprint_revision_1",
        "rubric_revision_ref": "rubric_revision_1",
        "criteria": {
            "criterion_evidence_support": {
                "criterion_revision_ref": "criterion_evidence_support_revision_1",
                "criterion_sha256": "b" * 64,
                "category_refs": ["category_not_supported", "category_supported"],
            },
            "criterion_safety": {
                "criterion_revision_ref": "criterion_safety_revision_1",
                "criterion_sha256": "c" * 64,
                "category_refs": ["category_unsafe", "category_safe"],
            },
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
                "category_anchor_ref": "category_supported",
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


def test_criterion_set_binding_is_nonempty_exact_and_content_addressed() -> None:
    """A rater receives exact criterion revisions, digests, and categories."""
    binding = CriterionSetExecutionBinding.from_mapping(_criterion_set_payload())
    assert binding.criterion_refs == (
        "criterion_evidence_support",
        "criterion_safety",
    )
    assert binding.criterion_set_sha256 == "a" * 64
    assert binding.criteria[0].category_refs == (
        "category_not_supported",
        "category_supported",
    )

    empty = _criterion_set_payload()
    empty["criteria"] = {}
    with pytest.raises(EvaluationCriterionBindingError) as caught:
        CriterionSetExecutionBinding.from_mapping(empty)
    assert caught.value.code == "invalid_criterion_set"

    malformed = _criterion_set_payload()
    malformed["criterion_set_sha256"] = "not-a-digest"
    with pytest.raises(EvaluationCriterionBindingError) as caught:
        CriterionSetExecutionBinding.from_mapping(malformed)
    assert caught.value.code == "invalid_sha256"


def test_rater_invocation_requires_the_exact_run_item_and_criterion_set() -> None:
    """An observation is unusable without exact run, item, and criterion meaning."""
    invocation = RaterInvocation.from_mapping(_invocation_payload())
    assert invocation.evaluation_run_snapshot_ref == "evaluation_run_snapshot_1"
    assert invocation.item_instance_ref == "evaluation_item_1"
    assert invocation.criterion_set.criterion_set_snapshot_ref == (
        "criterion_set_snapshot_1"
    )
    assert invocation.to_payload()["criterion_set"]["criterion_set_sha256"] == (
        "a" * 64
    )

    payload = _invocation_payload()
    del payload["criterion_set"]
    with pytest.raises(RaterObservationError) as caught:
        RaterInvocation.from_mapping(payload)
    assert caught.value.code == "missing_field"


def test_observations_must_cover_every_declared_criterion_exactly_once() -> None:
    """Missing or invented criteria cannot cross the observation boundary."""
    missing = _invocation_payload()
    observations = dict(missing["observations"])  # type: ignore[arg-type]
    observations.pop("criterion_safety")
    missing["observations"] = observations
    with pytest.raises(RaterObservationError) as caught:
        RaterInvocation.from_mapping(missing)
    assert caught.value.code == "criterion_coverage_mismatch"

    extra = _invocation_payload()
    observations = dict(extra["observations"])  # type: ignore[arg-type]
    observations["criterion_invented"] = observations["criterion_safety"]
    extra["observations"] = observations
    with pytest.raises(RaterObservationError) as caught:
        RaterInvocation.from_mapping(extra)
    assert caught.value.code == "criterion_coverage_mismatch"


def test_observed_categories_must_be_admitted_by_the_bound_criterion() -> None:
    """A provider cannot invent a category or borrow one from another criterion."""
    payload = _invocation_payload()
    observations = dict(payload["observations"])  # type: ignore[arg-type]
    evidence = dict(observations["criterion_evidence_support"])
    evidence["category_anchor_ref"] = "category_safe"
    observations["criterion_evidence_support"] = evidence
    payload["observations"] = observations

    with pytest.raises(RaterObservationError) as caught:
        RaterInvocation.from_mapping(payload)
    assert caught.value.code == "category_not_admitted"


def test_rubric_and_blueprint_binding_cannot_be_substituted() -> None:
    """The invocation rubric must be the one frozen by its criterion-set snapshot."""
    payload = _invocation_payload()
    payload["rubric_revision_ref"] = "rubric_revision_2"
    with pytest.raises(RaterObservationError) as caught:
        RaterInvocation.from_mapping(payload)
    assert caught.value.code == "criterion_set_rubric_mismatch"


def test_criterion_binding_rejects_duplicate_categories_and_foreign_values() -> None:
    """Criterion bindings are bounded typed values rather than loose dictionaries."""
    with pytest.raises(EvaluationCriterionBindingError) as caught:
        CriterionExecutionBinding.from_mapping(
            {
                "criterion_revision_ref": "criterion_revision_1",
                "criterion_sha256": "a" * 64,
                "category_refs": ["category_one", "category_one"],
            },
            criterion_ref="criterion_one",
        )
    assert caught.value.code == "duplicate_reference"

    with pytest.raises(RaterObservationError) as caught:
        RaterInvocation(
            invocation_ref="rater_invocation_1",
            configuration=object(),  # type: ignore[arg-type]
            evaluation_run_snapshot_ref="evaluation_run_snapshot_1",
            item_instance_ref="evaluation_item_1",
            task_revision_ref="task_revision_1",
            rubric_revision_ref="rubric_revision_1",
            criterion_set=object(),  # type: ignore[arg-type]
            response_evidence_ref="response_evidence_1",
            observations=(),
        )
    assert caught.value.code in {"invalid_configuration", "invalid_criterion_set"}
