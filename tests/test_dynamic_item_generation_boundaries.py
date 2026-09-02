"""Fail-closed resource and identity boundaries for dynamic generation."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

import contextual_orchestrator.dynamic_item_generation as generation
from contextual_orchestrator.dynamic_item_generation import (
    DYNAMIC_ITEM_GENERATION_CONTRACT_V1,
    MAX_GENERATION_CRITERIA,
    MAX_GENERATION_REFERENCES,
    DynamicItemGenerationError,
    DynamicItemGenerationInvocation,
)


def _criterion(seed: str) -> dict[str, object]:
    """Return one complete criterion for boundary tests."""
    return {
        "criterion_revision_ref": f"{seed}_revision",
        "definition_ref": f"{seed}_definition",
        "definition_sha256": "1" * 64,
        "admissible_evidence_rule_ref": f"{seed}_evidence",
        "admissible_evidence_rule_sha256": "2" * 64,
        "exclusion_rule_ref": f"{seed}_exclusion",
        "exclusion_rule_sha256": "3" * 64,
        "response_semantics_ref": f"{seed}_semantics",
        "response_semantics_sha256": "4" * 64,
        "abstention_rule_ref": f"{seed}_abstention",
        "abstention_rule_sha256": "5" * 64,
        "not_observable_rule_ref": f"{seed}_not_observable",
        "not_observable_rule_sha256": "6" * 64,
        "categories": {
            f"{seed}_zero": {
                "definition_ref": f"{seed}_zero_definition",
                "definition_sha256": "7" * 64,
                "order_index": 0,
            },
            f"{seed}_one": {
                "definition_ref": f"{seed}_one_definition",
                "definition_sha256": "8" * 64,
                "order_index": 1,
            },
        },
    }


def _payload() -> dict[str, Any]:
    """Return one minimal valid criterion-bound generation payload."""
    return {
        "contract_id": DYNAMIC_ITEM_GENERATION_CONTRACT_V1,
        "invocation_ref": "invocation",
        "configuration": {
            "generator_family_ref": "family",
            "provider_ref": "provider",
            "model_revision_ref": "model",
            "implementation_revision_ref": "implementation",
            "instruction_revision_ref": "instruction",
            "response_schema_revision_ref": "schema",
            "workflow_mode_ref": "workflow",
            "modality_channel_ref": "text",
        },
        "blueprint_revision_ref": "blueprint",
        "criterion_set": {
            "criterion_set_snapshot_ref": "criterion_set",
            "criterion_set_sha256": "a" * 64,
            "blueprint_revision_ref": "blueprint",
            "rubric_revision_ref": "rubric",
            "intended_use_ref": "intended_use",
            "construct_ref": "construct",
            "population_scope_ref": "population",
            "language_scope_ref": "language",
            "domain_scope_ref": "domain",
            "criteria": {"criterion": _criterion("criterion")},
        },
        "target_criterion_refs": ["criterion"],
        "source_snapshot_refs": [],
        "retrieval_context_refs": [],
        "attempt_refs": ["attempt"],
        "seed_ref": None,
        "status": "generated",
        "generated_item_ref": "item",
        "generated_content_ref": "content",
        "generated_content_sha256": "b" * 64,
        "reason_ref": None,
    }


def _code(payload: dict[str, Any]) -> str:
    """Return one stable error code."""
    with pytest.raises(DynamicItemGenerationError) as caught:
        DynamicItemGenerationInvocation.from_mapping(payload)
    return caught.value.code


@pytest.mark.parametrize(
    "invalid_ref",
    (
        "",
        " ref",
        "ref ",
        "\ufeffref",
        "ref\ufeff",
        "line\nbreak",
        "\ud800",
        "left\u200bright",
        "x" * 257,
    ),
)
def test_exact_references_reject_aliases_controls_surrogates_and_excess(
    invalid_ref: str,
) -> None:
    """Opaque references are never normalized or accepted beyond their budget."""
    payload = _payload()
    payload["invocation_ref"] = invalid_ref
    assert _code(payload) == "invalid_reference"


def test_complete_lowercase_digests_are_required_everywhere() -> None:
    """Content and criterion meaning cannot be identified by partial digests."""
    for path in (
        ("generated_content_sha256",),
        ("criterion_set", "criterion_set_sha256"),
        (
            "criterion_set",
            "criteria",
            "criterion",
            "definition_sha256",
        ),
    ):
        payload = _payload()
        cursor: dict[str, Any] = payload
        for component in path[:-1]:
            cursor = cursor[component]
        cursor[path[-1]] = "A" * 64
        assert _code(payload) == "invalid_sha256"


def test_reference_collections_are_typed_unique_nonempty_and_bounded() -> None:
    """Attempts and criterion targets retain strict bounded identity."""
    for field in (
        "target_criterion_refs",
        "attempt_refs",
    ):
        payload = _payload()
        payload[field] = []
        assert _code(payload) == "invalid_references"

        payload = _payload()
        payload[field] = ["same", "same"]
        assert _code(payload) == "duplicate_reference"

        payload = _payload()
        payload[field] = "not-an-array"
        assert _code(payload) == "invalid_references"

    payload = _payload()
    payload["attempt_refs"] = [
        f"attempt_{index}" for index in range(MAX_GENERATION_REFERENCES + 1)
    ]
    assert _code(payload) == "invalid_references"

    criteria = {
        f"criterion_{index}": _criterion(f"criterion_{index}")
        for index in range(MAX_GENERATION_CRITERIA + 1)
    }
    payload = _payload()
    payload["criterion_set"]["criteria"] = criteria
    payload["target_criterion_refs"] = list(criteria)
    assert _code(payload) == "invalid_criterion_set"


def test_contract_configuration_and_domain_types_fail_closed() -> None:
    """Incompatible contracts and foreign direct domain objects are rejected."""
    payload = _payload()
    payload["contract_id"] = "wrong/v1"
    assert _code(payload) == "contract_incompatible"

    payload = _payload()
    del payload["configuration"]["provider_ref"]
    assert _code(payload) == "missing_field"

    payload = _payload()
    payload["configuration"]["temperature"] = 0.2
    assert _code(payload) == "unknown_field"


def test_generated_content_identity_and_failure_reason_types_are_strict() -> None:
    """Terminal states cannot pass non-string references through optional paths."""
    payload = _payload()
    payload["generated_item_ref"] = object()
    assert _code(payload) == "invalid_reference"

    payload = _payload()
    payload["generated_content_sha256"] = object()
    assert _code(payload) == "invalid_sha256"

    payload = _payload()
    payload.update(
        status="failed",
        generated_item_ref=None,
        generated_content_ref=None,
        generated_content_sha256=None,
        reason_ref=object(),
    )
    assert _code(payload) == "invalid_reference"


def test_public_generation_module_has_complete_docstrings() -> None:
    """Every function and class in the new public module is documented."""
    source_path = Path(generation.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    missing = [
        f"{node.name}@{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and ast.get_docstring(node) is None
    ]
    assert missing == []
