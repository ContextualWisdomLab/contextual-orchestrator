"""Contracts for criterion-bound dynamic item generation evidence."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from contextual_orchestrator.dynamic_item_generation import (
    DYNAMIC_ITEM_GENERATION_CONTRACT_V1,
    DynamicItemGenerationError,
    DynamicItemGenerationInvocation,
    GenerationConfigurationIdentity,
    GenerationStatus,
)
from contextual_orchestrator.evaluation_criterion_binding import (
    CriterionSetExecutionBinding,
)


def _criterion(seed: str) -> dict[str, object]:
    """Return a complete content-addressed criterion."""
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
            f"{seed}_not_supported": {
                "definition_ref": f"{seed}_not_supported_definition",
                "definition_sha256": "7" * 64,
                "order_index": 0,
            },
            f"{seed}_supported": {
                "definition_ref": f"{seed}_supported_definition",
                "definition_sha256": "8" * 64,
                "order_index": 1,
            },
        },
    }


def _criterion_set() -> dict[str, object]:
    """Return a non-empty immutable criterion set."""
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
            "criterion_evidence_support": _criterion("criterion_evidence_support"),
            "criterion_safety": _criterion("criterion_safety"),
        },
    }


def _configuration() -> dict[str, str]:
    """Return one exact generator configuration."""
    return {
        "generator_family_ref": "generator_family_1",
        "provider_ref": "provider_1",
        "model_revision_ref": "model_revision_1",
        "implementation_revision_ref": "implementation_revision_1",
        "instruction_revision_ref": "instruction_revision_1",
        "response_schema_revision_ref": "response_schema_revision_1",
        "workflow_mode_ref": "workflow_mode_1",
        "modality_channel_ref": "modality_text_1",
    }


def _payload(status: str = "generated") -> dict[str, Any]:
    """Return one criterion-bound terminal generation payload."""
    generated = status == "generated"
    return {
        "contract_id": DYNAMIC_ITEM_GENERATION_CONTRACT_V1,
        "invocation_ref": "generation_invocation_1",
        "configuration": _configuration(),
        "blueprint_revision_ref": "evaluation_blueprint_revision_1",
        "criterion_set": _criterion_set(),
        "target_criterion_refs": [
            "criterion_evidence_support",
            "criterion_safety",
        ],
        "source_snapshot_refs": ["source_snapshot_1"],
        "retrieval_context_refs": ["retrieval_context_1"],
        "attempt_refs": ["attempt_1", "attempt_2"],
        "seed_ref": "seed_provenance_1",
        "status": status,
        "generated_item_ref": "generated_item_1" if generated else None,
        "generated_content_ref": "generated_content_1" if generated else None,
        "generated_content_sha256": "b" * 64 if generated else None,
        "reason_ref": None if generated else f"{status}_reason_1",
    }


def _code(payload: dict[str, Any]) -> str:
    """Return the stable error code for one invalid invocation payload."""
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(payload)
    return caught.value.code


def test_generated_invocation_round_trips_exact_criteria_and_provenance() -> None:
    """A generated item retains exact criterion meaning and all attempt evidence."""
    payload = _payload()
    invocation = DynamicItemGenerationInvocation.from_mapping(payload)
    assert invocation.status is GenerationStatus.GENERATED
    assert invocation.to_payload() == payload
    assert invocation.criterion_set.criterion_refs == (
        "criterion_evidence_support",
        "criterion_safety",
    )


def test_failed_and_abstained_invocations_preserve_denominator_evidence() -> None:
    """Non-generated terminal states retain criteria, attempts, and a reason."""
    for status in ("failed", "abstained"):
        payload = _payload(status)
        invocation = DynamicItemGenerationInvocation.from_mapping(payload)
        assert invocation.status.value == status
        assert invocation.generated_content_ref is None
        assert invocation.reason_ref == f"{status}_reason_1"
        assert invocation.target_criterion_refs == (
            "criterion_evidence_support",
            "criterion_safety",
        )


def test_status_content_and_reason_coupling_fail_closed() -> None:
    """Generation evidence cannot manufacture content or hide failure reasons."""
    generated_reason = _payload()
    generated_reason["reason_ref"] = "failure_reason"
    assert _code(generated_reason) == "generated_has_reason"

    incomplete = _payload()
    incomplete["generated_content_sha256"] = None
    assert _code(incomplete) == "generated_content_incomplete"

    failed_content = _payload("failed")
    failed_content["generated_item_ref"] = "manufactured_item"
    assert _code(failed_content) == "non_generated_has_content"

    failed_reason = _payload("failed")
    failed_reason["reason_ref"] = None
    assert _code(failed_reason) == "non_generated_requires_reason"


def test_generation_requires_exact_criterion_set_and_coverage() -> None:
    """No item is generated before criteria, evidence rules, and categories exist."""
    missing = _payload()
    del missing["criterion_set"]
    assert _code(missing) == "missing_field"

    empty = _payload()
    empty["criterion_set"]["criteria"] = {}
    assert _code(empty) == "invalid_criterion_set"

    incomplete = _payload()
    del incomplete["criterion_set"]["criteria"]["criterion_safety"][
        "abstention_rule_sha256"
    ]
    assert _code(incomplete) == "missing_field"

    blueprint = _payload()
    blueprint["blueprint_revision_ref"] = "evaluation_blueprint_revision_2"
    assert _code(blueprint) == "criterion_set_blueprint_mismatch"

    for refs in (
        ["criterion_evidence_support"],
        ["criterion_evidence_support", "criterion_safety", "criterion_extra"],
        ["criterion_safety", "criterion_evidence_support"],
    ):
        changed = _payload()
        changed["target_criterion_refs"] = refs
        assert _code(changed) == "criterion_coverage_mismatch"


def test_configuration_and_acl_are_closed_and_typed() -> None:
    """Provider payloads cannot add decision authority or foreign fields."""
    configuration = GenerationConfigurationIdentity.from_mapping(_configuration())
    assert configuration.to_payload() == _configuration()

    unknown = _payload()
    unknown["unknown_field"] = "x"
    assert _code(unknown) == "unknown_field"

    authority = _payload()
    authority["score"] = 1
    assert _code(authority) == "authority_leakage"

    wrong_configuration = _payload()
    wrong_configuration["configuration"] = []
    assert _code(wrong_configuration) == "invalid_object"

    wrong_criterion_set = _payload()
    wrong_criterion_set["criterion_set"] = []
    assert _code(wrong_criterion_set) == "invalid_object"

    direct = _payload()
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation(
            invocation_ref=direct["invocation_ref"],
            configuration=object(),  # type: ignore[arg-type]
            blueprint_revision_ref=direct["blueprint_revision_ref"],
            criterion_set=CriterionSetExecutionBinding.from_mapping(
                direct["criterion_set"]
            ),
            target_criterion_refs=direct["target_criterion_refs"],
            source_snapshot_refs=direct["source_snapshot_refs"],
            retrieval_context_refs=direct["retrieval_context_refs"],
            attempt_refs=direct["attempt_refs"],
            seed_ref=direct["seed_ref"],
            status=direct["status"],
            generated_item_ref=direct["generated_item_ref"],
            generated_content_ref=direct["generated_content_ref"],
            generated_content_sha256=direct["generated_content_sha256"],
            reason_ref=direct["reason_ref"],
        )
    assert caught.value.code == "invalid_configuration"


def test_raw_json_rejects_duplicates_depth_and_invalid_values() -> None:
    """Raw generator JSON cannot exploit duplicate-member or nesting ambiguity."""
    payload = _payload()
    assert DynamicItemGenerationInvocation.from_json(json.dumps(payload)).to_payload() == (
        payload
    )

    duplicate = '{"contract_id":"a","contract_id":"b"}'
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_json(duplicate)
    assert caught.value.code == "duplicate_object_member"

    nested = "[" * 65 + "0" + "]" * 65
    for invalid in (nested, "{", object()):
        with pytest.raises(DynamicItemGenerationError) as caught:
            DynamicItemGenerationInvocation.from_json(invalid)  # type: ignore[arg-type]
        assert caught.value.code == "invalid_json"


def test_invocation_detaches_all_nested_caller_collections() -> None:
    """Caller mutation cannot rewrite criterion or attempt identity after admission."""
    payload = _payload()
    expected = deepcopy(payload)
    invocation = DynamicItemGenerationInvocation.from_mapping(payload)
    payload["target_criterion_refs"].append("criterion_invented")
    payload["attempt_refs"].append("attempt_3")
    payload["criterion_set"]["criteria"]["criterion_safety"]["definition_ref"] = (
        "mutated"
    )
    assert invocation.to_payload() == expected
