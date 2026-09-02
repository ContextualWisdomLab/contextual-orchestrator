"""Criterion-set binding contracts for dynamic item generation."""

from __future__ import annotations

import pytest

from contextual_orchestrator.dynamic_item_generation import (
    DYNAMIC_ITEM_GENERATION_CONTRACT_V1,
    DynamicItemGenerationError,
    DynamicItemGenerationInvocation,
)
from contextual_orchestrator.evaluation_criterion_binding import (
    CriterionSetExecutionBinding,
)


def _criterion_set_payload() -> dict[str, object]:
    """Return one exact source-text-free criterion-set binding."""
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


def _payload() -> dict[str, object]:
    """Return one successful criterion-bound generation invocation."""
    return {
        "contract_id": DYNAMIC_ITEM_GENERATION_CONTRACT_V1,
        "invocation_ref": "generation_invocation_1",
        "configuration": {
            "generator_family_ref": "generator_family_1",
            "provider_ref": "provider_1",
            "model_revision_ref": "model_revision_1",
            "implementation_revision_ref": "implementation_revision_1",
            "instruction_revision_ref": "instruction_revision_1",
            "response_schema_revision_ref": "response_schema_revision_1",
            "workflow_mode_ref": "workflow_mode_1",
            "modality_channel_ref": "modality_text_1",
        },
        "blueprint_revision_ref": "evaluation_blueprint_revision_1",
        "criterion_set": _criterion_set_payload(),
        "criterion_refs": [
            "criterion_evidence_support",
            "criterion_safety",
        ],
        "source_snapshot_refs": ["source_snapshot_1"],
        "retrieval_context_refs": ["retrieval_context_1"],
        "attempt_refs": ["attempt_1"],
        "seed_ref": None,
        "status": "generated",
        "generated_item_ref": "evaluation_item_1",
        "generated_content_ref": "generated_content_1",
        "generated_content_sha256": "d" * 64,
        "reason_ref": None,
    }


def test_generation_requires_exact_criterion_set_identity_and_digest() -> None:
    """A generated item has no evaluable meaning without its frozen criteria."""
    invocation = DynamicItemGenerationInvocation.from_mapping(_payload())
    assert invocation.criterion_set.criterion_set_snapshot_ref == (
        "criterion_set_snapshot_1"
    )
    assert invocation.criterion_set.criterion_set_sha256 == "a" * 64
    assert invocation.criterion_refs == (
        "criterion_evidence_support",
        "criterion_safety",
    )
    assert invocation.to_payload()["criterion_set"]["criterion_set_sha256"] == (
        "a" * 64
    )

    payload = _payload()
    del payload["criterion_set"]
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(payload)
    assert caught.value.code == "missing_field"


def test_generation_rejects_unknown_criteria_and_blueprint_substitution() -> None:
    """A generator cannot invent a target criterion or switch blueprints."""
    unknown = _payload()
    unknown["criterion_refs"] = ["criterion_invented"]
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(unknown)
    assert caught.value.code == "criterion_not_registered"

    foreign = _payload()
    foreign["blueprint_revision_ref"] = "evaluation_blueprint_revision_2"
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(foreign)
    assert caught.value.code == "criterion_set_blueprint_mismatch"


def test_generation_requires_at_least_one_registered_criterion() -> None:
    """An item-generation request cannot target an empty construct."""
    payload = _payload()
    payload["criterion_refs"] = []
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(payload)
    assert caught.value.code == "invalid_references"


def test_non_success_generation_retains_the_same_criterion_binding() -> None:
    """Failed and abstained attempts stay in the denominator under exact criteria."""
    for status in ("failed", "abstained"):
        payload = _payload()
        payload.update(
            {
                "status": status,
                "generated_item_ref": None,
                "generated_content_ref": None,
                "generated_content_sha256": None,
                "reason_ref": f"{status}_reason_1",
            }
        )
        invocation = DynamicItemGenerationInvocation.from_mapping(payload)
        assert invocation.criterion_set.criterion_set_sha256 == "a" * 64
        assert invocation.criterion_refs == (
            "criterion_evidence_support",
            "criterion_safety",
        )


def test_direct_construction_rejects_foreign_criterion_binding() -> None:
    """The typed path cannot bypass criterion-set admission."""
    payload = _payload()
    criterion_set = CriterionSetExecutionBinding.from_mapping(
        _criterion_set_payload()
    )
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation(
            invocation_ref="generation_invocation_1",
            configuration=object(),  # type: ignore[arg-type]
            blueprint_revision_ref="evaluation_blueprint_revision_1",
            criterion_set=criterion_set,
            criterion_refs=("criterion_evidence_support",),
            source_snapshot_refs=(),
            retrieval_context_refs=(),
            attempt_refs=("attempt_1",),
            seed_ref=None,
            status="generated",
            generated_item_ref="evaluation_item_1",
            generated_content_ref="generated_content_1",
            generated_content_sha256="d" * 64,
            reason_ref=None,
        )
    assert caught.value.code == "invalid_configuration"
