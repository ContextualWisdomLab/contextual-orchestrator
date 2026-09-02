"""Contracts for provider-neutral dynamic item-generation evidence."""

from __future__ import annotations

import json

import pytest

from contextual_orchestrator.dynamic_item_generation import (
    DYNAMIC_ITEM_GENERATION_CONTRACT_V1,
    DynamicItemGenerationError,
    DynamicItemGenerationInvocation,
    GenerationConfigurationIdentity,
    GenerationStatus,
)

_SHA = "a" * 64


def _configuration() -> GenerationConfigurationIdentity:
    """Return one exact reusable generator configuration identity."""
    return GenerationConfigurationIdentity(
        generator_family_ref="generator_family_alpha",
        provider_ref="provider_alpha",
        model_revision_ref="model_revision_alpha",
        implementation_revision_ref="implementation_revision_alpha",
        instruction_revision_ref="instruction_revision_alpha",
        response_schema_revision_ref="response_schema_revision_alpha",
        workflow_mode_ref="workflow_mode_route",
        modality_channel_ref="modality_text",
    )


def _success_payload() -> dict[str, object]:
    """Return one successful untrusted provider-neutral envelope."""
    return {
        "contract_id": DYNAMIC_ITEM_GENERATION_CONTRACT_V1,
        "invocation_ref": "generation_invocation_alpha",
        "configuration": _configuration().to_payload(),
        "blueprint_revision_ref": "evaluation_blueprint_revision_1",
        "source_snapshot_refs": ["source_snapshot_1"],
        "retrieval_context_refs": ["retrieval_context_1"],
        "attempt_refs": ["attempt_1", "attempt_2"],
        "seed_ref": "seed_recorded_not_deterministic",
        "status": "generated",
        "generated_item_ref": "evaluation_item_alpha",
        "generated_content_ref": "generated_content_alpha",
        "generated_content_sha256": _SHA,
        "reason_ref": None,
    }


def test_generated_invocation_freezes_content_and_all_attempts() -> None:
    """Successful generation records exact content and preserves failed/fallback attempts."""
    payload = _success_payload()
    invocation = DynamicItemGenerationInvocation.from_mapping(payload)

    payload["attempt_refs"] = ["mutated_attempt"]
    assert invocation.status is GenerationStatus.GENERATED
    assert invocation.attempt_refs == ("attempt_1", "attempt_2")
    assert invocation.generated_content_sha256 == _SHA
    assert invocation.seed_ref == "seed_recorded_not_deterministic"
    assert invocation.to_payload()["generated_item_ref"] == "evaluation_item_alpha"


def test_seed_is_provenance_and_deterministic_claims_are_rejected() -> None:
    """A provider seed never authorizes a deterministic-regeneration field."""
    payload = _success_payload()
    payload["deterministic"] = True

    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(payload)
    assert caught.value.code == "authority_leakage"


def test_generation_boundary_rejects_score_gold_anchor_and_adjudication_fields() -> None:
    """The orchestrator cannot approve, score, adjudicate, or promote generated items."""
    for forbidden in (
        "score",
        "gold",
        "anchor",
        "approved",
        "reference_status",
        "adjudication_ref",
        "validation_evidence_ref",
    ):
        payload = _success_payload()
        payload[forbidden] = "forbidden"
        with pytest.raises(DynamicItemGenerationError) as caught:
            DynamicItemGenerationInvocation.from_mapping(payload)
        assert caught.value.code == "authority_leakage"


def test_failed_and_abstained_invocations_preserve_denominator_without_content() -> None:
    """Non-success outcomes retain a reason and cannot manufacture item content."""
    for status in (GenerationStatus.FAILED, GenerationStatus.ABSTAINED):
        payload = _success_payload()
        payload.update(
            {
                "status": status.value,
                "generated_item_ref": None,
                "generated_content_ref": None,
                "generated_content_sha256": None,
                "reason_ref": f"{status.value}_reason_1",
            }
        )
        invocation = DynamicItemGenerationInvocation.from_mapping(payload)
        assert invocation.status is status
        assert invocation.reason_ref == f"{status.value}_reason_1"
        assert invocation.generated_item_ref is None

        payload["generated_item_ref"] = "manufactured_item"
        with pytest.raises(DynamicItemGenerationError) as caught:
            DynamicItemGenerationInvocation.from_mapping(payload)
        assert caught.value.code == "non_generated_has_content"


def test_generated_status_requires_complete_content_identity() -> None:
    """A generated outcome is not successful evidence until every content identity exists."""
    for field in (
        "generated_item_ref",
        "generated_content_ref",
        "generated_content_sha256",
    ):
        payload = _success_payload()
        payload[field] = None
        with pytest.raises(DynamicItemGenerationError) as caught:
            DynamicItemGenerationInvocation.from_mapping(payload)
        assert caught.value.code == "generated_content_incomplete"

    payload = _success_payload()
    payload["reason_ref"] = "unexpected_reason"
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(payload)
    assert caught.value.code == "generated_has_reason"


def test_raw_json_rejects_duplicate_members_and_invalid_digest() -> None:
    """Provider JSON cannot use duplicate keys or a partial content fingerprint."""
    duplicate = json.dumps(_success_payload()).replace(
        '"status": "generated"',
        '"status": "generated", "status": "failed"',
    )
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_json(duplicate)
    assert caught.value.code == "duplicate_object_member"

    payload = _success_payload()
    payload["generated_content_sha256"] = "A" * 64
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(payload)
    assert caught.value.code == "invalid_sha256"


def test_configuration_and_reference_collections_fail_closed() -> None:
    """Configuration identity and provenance collections are exact and unique."""
    payload = _success_payload()
    payload["attempt_refs"] = ["attempt_1", "attempt_1"]
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(payload)
    assert caught.value.code == "duplicate_reference"

    payload = _success_payload()
    configuration = dict(payload["configuration"])  # type: ignore[arg-type]
    configuration["provider_ref"] = " provider_alpha"
    payload["configuration"] = configuration
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(payload)
    assert caught.value.code == "invalid_reference"


def test_direct_invocation_construction_still_replays_invariants() -> None:
    """Direct typed construction validates status/content coupling and copies arrays."""
    attempts = ["attempt_1"]
    invocation = DynamicItemGenerationInvocation(
        invocation_ref="generation_invocation_alpha",
        configuration=_configuration(),
        blueprint_revision_ref="evaluation_blueprint_revision_1",
        source_snapshot_refs=["source_snapshot_1"],
        retrieval_context_refs=[],
        attempt_refs=attempts,
        seed_ref=None,
        status=GenerationStatus.GENERATED,
        generated_item_ref="evaluation_item_alpha",
        generated_content_ref="generated_content_alpha",
        generated_content_sha256=_SHA,
        reason_ref=None,
    )
    attempts.append("attempt_2")
    assert invocation.attempt_refs == ("attempt_1",)

    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation(
            invocation_ref="generation_invocation_alpha",
            configuration=_configuration(),
            blueprint_revision_ref="evaluation_blueprint_revision_1",
            source_snapshot_refs=["source_snapshot_1"],
            retrieval_context_refs=[],
            attempt_refs=["attempt_1"],
            seed_ref=None,
            status=GenerationStatus.FAILED,
            generated_item_ref="evaluation_item_alpha",
            generated_content_ref=None,
            generated_content_sha256=None,
            reason_ref="failed_reason_1",
        )
    assert caught.value.code == "non_generated_has_content"
