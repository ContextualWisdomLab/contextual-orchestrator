"""Fail-closed boundaries for provider-neutral item-generation evidence."""

from __future__ import annotations

import json
from typing import Any

import pytest

from contextual_orchestrator.dynamic_item_generation import (
    DYNAMIC_ITEM_GENERATION_CONTRACT_V1,
    DynamicItemGenerationError,
    DynamicItemGenerationInvocation,
    GenerationConfigurationIdentity,
    GenerationStatus,
)


def _configuration_payload() -> dict[str, Any]:
    return {
        "generator_family_ref": "generator_family_alpha",
        "provider_ref": "provider_alpha",
        "model_revision_ref": "model_revision_alpha",
        "implementation_revision_ref": "implementation_revision_alpha",
        "instruction_revision_ref": "instruction_revision_alpha",
        "response_schema_revision_ref": "response_schema_revision_alpha",
        "workflow_mode_ref": "workflow_mode_route",
        "modality_channel_ref": "modality_text",
    }


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_id": DYNAMIC_ITEM_GENERATION_CONTRACT_V1,
        "invocation_ref": "generation_invocation_alpha",
        "configuration": _configuration_payload(),
        "blueprint_revision_ref": "evaluation_blueprint_revision_1",
        "source_snapshot_refs": ["source_snapshot_1"],
        "retrieval_context_refs": ["retrieval_context_1"],
        "attempt_refs": ["attempt_1"],
        "seed_ref": None,
        "status": "generated",
        "generated_item_ref": "evaluation_item_alpha",
        "generated_content_ref": "generated_content_alpha",
        "generated_content_sha256": "a" * 64,
        "reason_ref": None,
    }
    payload.update(overrides)
    return payload


def test_json_parser_handles_escaped_strings_and_rejects_bad_envelopes() -> None:
    payload = _payload()
    payload["configuration"]["provider_ref"] = 'provider_"alpha'  # type: ignore[index]
    parsed = DynamicItemGenerationInvocation.from_json(json.dumps(payload))
    assert parsed.configuration.provider_ref == 'provider_"alpha'

    for value in (object(), "{not-json", "[" * 65 + "0" + "]" * 65):
        with pytest.raises(DynamicItemGenerationError) as caught:
            DynamicItemGenerationInvocation.from_json(value)  # type: ignore[arg-type]
        assert caught.value.code == "invalid_json"

    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_json("[]")
    assert caught.value.code == "invalid_object"


def test_mapping_and_unknown_field_boundaries() -> None:
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping({1: "not-a-string-key"})
    assert caught.value.code == "invalid_object_key"

    payload = _payload(unexpected_field="value")
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(payload)
    assert caught.value.code == "unknown_field"

    payload = _payload()
    del payload["reason_ref"]
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(payload)
    assert caught.value.code == "missing_field"


def test_configuration_requires_exact_complete_known_fields() -> None:
    payload = _configuration_payload()
    del payload["provider_ref"]
    with pytest.raises(DynamicItemGenerationError) as caught:
        GenerationConfigurationIdentity.from_mapping(payload)
    assert caught.value.code == "missing_field"

    payload = _configuration_payload()
    payload["unexpected"] = "value"
    with pytest.raises(DynamicItemGenerationError) as caught:
        GenerationConfigurationIdentity.from_mapping(payload)
    assert caught.value.code == "unknown_field"

    with pytest.raises(DynamicItemGenerationError) as caught:
        GenerationConfigurationIdentity.from_mapping([])
    assert caught.value.code == "invalid_object"


@pytest.mark.parametrize(
    "invalid",
    (
        "",
        " provider_alpha",
        "provider_alpha ",
        "\ufeffprovider_alpha",
        "provider_alpha\ufeff",
        "line\nbreak",
        "\ud800",
        "x" * 257,
        object(),
    ),
)
def test_reference_values_are_exact_bounded_unicode_scalars(invalid: object) -> None:
    payload = _configuration_payload()
    payload["provider_ref"] = invalid
    with pytest.raises(DynamicItemGenerationError) as caught:
        GenerationConfigurationIdentity.from_mapping(payload)
    assert caught.value.code == "invalid_reference"


def test_reference_arrays_are_typed_nonempty_when_required_and_bounded() -> None:
    for attempts in ("attempt_1", [], ["attempt_1"] * 257):
        payload = _payload(attempt_refs=attempts)
        with pytest.raises(DynamicItemGenerationError) as caught:
            DynamicItemGenerationInvocation.from_mapping(payload)
        assert caught.value.code == "invalid_references"


def test_status_digest_and_terminal_state_coupling_fail_closed() -> None:
    for status in (object(), "unknown"):
        with pytest.raises(DynamicItemGenerationError) as caught:
            DynamicItemGenerationInvocation.from_mapping(_payload(status=status))
        assert caught.value.code == "invalid_status"

    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(
            _payload(generated_content_sha256=object())
        )
    assert caught.value.code == "invalid_sha256"

    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(
            _payload(
                status=GenerationStatus.FAILED,
                generated_item_ref=None,
                generated_content_ref=None,
                generated_content_sha256=None,
                reason_ref=None,
            )
        )
    assert caught.value.code == "non_generated_requires_reason"


def test_direct_constructor_rejects_contract_and_configuration_rebinding() -> None:
    configuration = GenerationConfigurationIdentity.from_mapping(_configuration_payload())
    common = {
        "invocation_ref": "generation_invocation_alpha",
        "configuration": configuration,
        "blueprint_revision_ref": "evaluation_blueprint_revision_1",
        "source_snapshot_refs": [],
        "retrieval_context_refs": [],
        "attempt_refs": ["attempt_1"],
        "seed_ref": None,
        "status": GenerationStatus.GENERATED,
        "generated_item_ref": "evaluation_item_alpha",
        "generated_content_ref": "generated_content_alpha",
        "generated_content_sha256": "a" * 64,
        "reason_ref": None,
    }
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation(**common, contract_id="wrong/v1")
    assert caught.value.code == "contract_incompatible"

    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation(**{**common, "configuration": object()})
    assert caught.value.code == "invalid_configuration"
