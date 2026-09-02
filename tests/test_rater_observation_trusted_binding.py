"""Regression contracts for trusted criterion binding and immutable identity."""

from __future__ import annotations

import hashlib
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
    RaterInvocation,
    RaterObservationError,
)


def _canonical_digest(payload: dict[str, Any]) -> str:
    """Hash the criterion-set content while excluding its digest field."""
    content = deepcopy(payload)
    content.pop("criterion_set_sha256", None)
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _category(seed: str, order_index: int) -> dict[str, object]:
    """Return one content-addressed response category."""
    return {
        "definition_ref": f"{seed}_definition",
        "definition_sha256": seed[0] * 64,
        "order_index": order_index,
    }


def _criterion(seed: str) -> dict[str, object]:
    """Return one complete substantive criterion."""
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


def _criterion_set(*, seed: str = "expected") -> dict[str, Any]:
    """Return a criterion set whose digest covers all admitted meaning."""
    payload: dict[str, Any] = {
        "criterion_set_snapshot_ref": f"{seed}_criterion_set_snapshot_1",
        "criterion_set_sha256": "",
        "blueprint_revision_ref": "evaluation_blueprint_revision_1",
        "rubric_revision_ref": "rubric_revision_1",
        "intended_use_ref": "intended_use_1",
        "construct_ref": f"{seed}_construct_1",
        "population_scope_ref": "population_scope_1",
        "language_scope_ref": "language_scope_1",
        "domain_scope_ref": "domain_scope_1",
        "criteria": {
            f"{seed}_criterion_evidence": _criterion(f"{seed}_criterion_evidence"),
            f"{seed}_criterion_safety": _criterion(f"{seed}_criterion_safety"),
        },
    }
    payload["criterion_set_sha256"] = _canonical_digest(payload)
    return payload


def _observation(category_ref: str) -> dict[str, object]:
    """Return one observed criterion result."""
    return {
        "status": "observed",
        "category_anchor_ref": category_ref,
        "evidence_reference_ids": ["evidence_1"],
        "uncertainty": "low",
        "review_signal_refs": [],
        "reason_ref": None,
    }


def _invocation(criterion_set: dict[str, Any]) -> dict[str, Any]:
    """Return a provider envelope that echoes one criterion-set identity."""
    criterion_refs = tuple(criterion_set["criteria"])
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
        "rubric_revision_ref": criterion_set["rubric_revision_ref"],
        "criterion_set": deepcopy(criterion_set),
        "response_evidence_ref": "response_evidence_1",
        "observations": {
            criterion_ref: _observation(f"{criterion_ref}_supported")
            for criterion_ref in criterion_refs
        },
    }


def _error_code(callable_: Any) -> str:
    """Return the stable code from one rejected boundary call."""
    with pytest.raises(
        (EvaluationCriterionBindingError, RaterObservationError)
    ) as caught:
        callable_()
    return caught.value.code


def test_criterion_set_digest_rejects_substantive_mutation() -> None:
    """A valid-looking old digest cannot survive a change in criterion meaning."""
    payload = _criterion_set()
    payload["criteria"]["expected_criterion_safety"]["definition_ref"] = "changed"

    assert _error_code(
        lambda: CriterionSetExecutionBinding.from_mapping(payload)
    ) == "criterion_set_digest_mismatch"


def test_category_order_is_covered_by_the_criterion_set_digest() -> None:
    """Swapping otherwise valid category positions changes the set identity."""
    payload = _criterion_set()
    categories = payload["criteria"]["expected_criterion_safety"]["categories"]
    categories["expected_criterion_safety_not_supported"]["order_index"] = 1
    categories["expected_criterion_safety_supported"]["order_index"] = 0

    assert _error_code(
        lambda: CriterionSetExecutionBinding.from_mapping(payload)
    ) == "criterion_set_digest_mismatch"


def test_public_binding_constructors_cannot_bypass_validation() -> None:
    """Only validated factories can create exact criterion-domain values."""
    with pytest.raises(ValueError):
        CategoryExecutionBinding(
            category_ref="category",
            definition_ref="definition",
            definition_sha256="a" * 64,
            order_index=0,
        )

    valid_set = CriterionSetExecutionBinding.from_mapping(_criterion_set())
    valid_criterion = valid_set.criteria[0]
    with pytest.raises(ValueError):
        CriterionExecutionBinding(
            criterion_ref=valid_criterion.criterion_ref,
            criterion_revision_ref=valid_criterion.criterion_revision_ref,
            definition_ref=valid_criterion.definition_ref,
            definition_sha256=valid_criterion.definition_sha256,
            admissible_evidence_rule_ref=valid_criterion.admissible_evidence_rule_ref,
            admissible_evidence_rule_sha256=(
                valid_criterion.admissible_evidence_rule_sha256
            ),
            exclusion_rule_ref=valid_criterion.exclusion_rule_ref,
            exclusion_rule_sha256=valid_criterion.exclusion_rule_sha256,
            response_semantics_ref=valid_criterion.response_semantics_ref,
            response_semantics_sha256=valid_criterion.response_semantics_sha256,
            abstention_rule_ref=valid_criterion.abstention_rule_ref,
            abstention_rule_sha256=valid_criterion.abstention_rule_sha256,
            not_observable_rule_ref=valid_criterion.not_observable_rule_ref,
            not_observable_rule_sha256=valid_criterion.not_observable_rule_sha256,
            categories=valid_criterion.categories,
        )

    with pytest.raises(ValueError):
        CriterionSetExecutionBinding(
            criterion_set_snapshot_ref=valid_set.criterion_set_snapshot_ref,
            criterion_set_sha256=valid_set.criterion_set_sha256,
            blueprint_revision_ref=valid_set.blueprint_revision_ref,
            rubric_revision_ref=valid_set.rubric_revision_ref,
            intended_use_ref=valid_set.intended_use_ref,
            construct_ref=valid_set.construct_ref,
            population_scope_ref=valid_set.population_scope_ref,
            language_scope_ref=valid_set.language_scope_ref,
            domain_scope_ref=valid_set.domain_scope_ref,
            criteria=valid_set.criteria,
        )


def test_admitted_binding_detects_object_level_tampering() -> None:
    """Frozen syntax cannot hide deliberate object-level mutation after admission."""
    binding = CriterionSetExecutionBinding.from_mapping(_criterion_set())
    object.__setattr__(binding.criteria[0], "definition_ref", "mutated_definition")

    assert _error_code(binding.to_payload) == "criterion_set_integrity_mismatch"


def test_provider_parser_requires_a_separately_trusted_criterion_set() -> None:
    """Provider output alone cannot become authoritative evaluation evidence."""
    payload = _invocation(_criterion_set())

    assert _error_code(
        lambda: RaterInvocation.from_mapping(payload)
    ) == "trusted_criterion_set_required"


def test_whole_criterion_substitution_is_rejected() -> None:
    """A matching malicious criterion set and observation set cannot replace policy."""
    expected = CriterionSetExecutionBinding.from_mapping(_criterion_set())
    substituted_set = _criterion_set(seed="substituted")
    substituted = _invocation(substituted_set)

    assert _error_code(
        lambda: RaterInvocation.from_mapping(
            substituted,
            expected_criterion_set=expected,
        )
    ) == "criterion_set_substitution"


def test_trusted_criterion_bound_invocation_round_trips() -> None:
    """The secure parser returns evidence only under the independently supplied set."""
    criterion_payload = _criterion_set()
    expected = CriterionSetExecutionBinding.from_mapping(criterion_payload)
    payload = _invocation(criterion_payload)

    invocation = RaterInvocation.from_mapping(
        payload,
        expected_criterion_set=expected,
    )
    assert invocation.criterion_set is expected
    assert invocation.to_payload() == payload

    encoded = json.dumps(payload)
    parsed = RaterInvocation.from_json(
        encoded,
        expected_criterion_set=expected,
    )
    assert parsed.to_payload() == payload
