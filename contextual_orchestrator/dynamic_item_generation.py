"""Provider-neutral criterion-bound dynamic item-generation evidence.

The module is an Anti-Corruption Layer for model, human, or algorithmic item
generators. It records exact generator configuration, immutable evaluation
criteria, input provenance, attempts, and generated-content identity while
structurally excluding scoring, adjudication, validation, anchor promotion, and
deterministic-regeneration authority.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .evaluation_criterion_binding import (
    CriterionSetExecutionBinding,
    EvaluationCriterionBindingError,
)

DYNAMIC_ITEM_GENERATION_CONTRACT_V1 = "cwl_dynamic_item_generation_invocation/v1"
MAX_GENERATION_REFERENCE_LENGTH = 256
MAX_GENERATION_REFERENCES = 256
MAX_GENERATION_CRITERIA = 128
MAX_GENERATION_JSON_DEPTH = 64

_PROHIBITED_AUTHORITY_FIELDS = frozenset(
    {
        "score",
        "final_score",
        "latent_trait",
        "gold",
        "golden",
        "anchor",
        "approved",
        "reference_status",
        "adjudication_ref",
        "validation_evidence_ref",
        "validation_evidence_refs",
        "deterministic",
        "regeneration_verified",
        "pass_fail",
        "certification",
        "employment_decision",
    }
)
_CONFIGURATION_FIELDS = frozenset(
    {
        "generator_family_ref",
        "provider_ref",
        "model_revision_ref",
        "implementation_revision_ref",
        "instruction_revision_ref",
        "response_schema_revision_ref",
        "workflow_mode_ref",
        "modality_channel_ref",
    }
)
_INVOCATION_FIELDS = frozenset(
    {
        "contract_id",
        "invocation_ref",
        "configuration",
        "blueprint_revision_ref",
        "criterion_set",
        "target_criterion_refs",
        "source_snapshot_refs",
        "retrieval_context_refs",
        "attempt_refs",
        "seed_ref",
        "status",
        "generated_item_ref",
        "generated_content_ref",
        "generated_content_sha256",
        "reason_ref",
    }
)


class GenerationStatus(str, Enum):
    """Terminal evidence state for one generator invocation."""

    GENERATED = "generated"
    ABSTAINED = "abstained"
    FAILED = "failed"


class DynamicItemGenerationError(ValueError):
    """Stable fail-closed error for item-generation contract violations."""

    def __init__(self, code: str, message: str) -> None:
        """Retain a bounded machine-readable rejection code."""
        self.code = code
        super().__init__(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object while rejecting duplicate member names."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DynamicItemGenerationError(
                "duplicate_object_member", "JSON objects must not repeat member names"
            )
        result[key] = value
    return result


def _json_depth_is_bounded(value: str) -> bool:
    """Check container nesting without counting bracket characters in strings."""
    depth = 0
    in_string = False
    escaped = False
    for character in value:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_GENERATION_JSON_DEPTH:
                return False
        elif character in "]}":
            depth -= 1
    return True


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    """Require one string-keyed mapping at the provider boundary."""
    if not isinstance(value, Mapping):
        raise DynamicItemGenerationError(
            "invalid_object", f"{field_name} must be an object"
        )
    if any(type(key) is not str for key in value):
        raise DynamicItemGenerationError(
            "invalid_object_key", f"{field_name} keys must be strings"
        )
    return value


def _reject_unknown_fields(
    payload: Mapping[str, Any], allowed: frozenset[str], field_name: str
) -> None:
    """Reject foreign authority before ordinary unknown-field failures."""
    unknown = set(payload) - allowed
    if unknown.intersection(_PROHIBITED_AUTHORITY_FIELDS):
        raise DynamicItemGenerationError(
            "authority_leakage",
            f"{field_name} must not contain scoring, gold, anchor, adjudication, "
            "validation, or deterministic-regeneration authority",
        )
    if unknown:
        raise DynamicItemGenerationError(
            "unknown_field",
            f"{field_name} contains unsupported fields: {sorted(unknown)}",
        )


def _reference(value: Any, field_name: str) -> str:
    """Validate one exact bounded opaque reference without normalization."""
    if type(value) is not str:
        raise DynamicItemGenerationError(
            "invalid_reference", f"{field_name} must be a string"
        )
    if (
        not value
        or value != value.strip()
        or value.startswith("\ufeff")
        or value.endswith("\ufeff")
        or len(value) > MAX_GENERATION_REFERENCE_LENGTH
        or any(
            unicodedata.category(character) in {"Cc", "Cs", "Cf"}
            for character in value
        )
    ):
        raise DynamicItemGenerationError(
            "invalid_reference",
            f"{field_name} must be an exact bounded opaque reference",
        )
    return value


def _optional_reference(value: Any, field_name: str) -> str | None:
    """Validate an optional opaque reference while preserving absence."""
    if value is None:
        return None
    return _reference(value, field_name)


def _reference_tuple(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool,
    maximum: int = MAX_GENERATION_REFERENCES,
) -> tuple[str, ...]:
    """Copy and validate a bounded unique reference collection."""
    if not isinstance(value, (list, tuple)):
        raise DynamicItemGenerationError(
            "invalid_references", f"{field_name} must be an array"
        )
    if (not allow_empty and not value) or len(value) > maximum:
        lower = 0 if allow_empty else 1
        raise DynamicItemGenerationError(
            "invalid_references",
            f"{field_name} must contain {lower}..{maximum} references",
        )
    normalized = tuple(_reference(item, field_name) for item in value)
    if len(set(normalized)) != len(normalized):
        raise DynamicItemGenerationError(
            "duplicate_reference", f"{field_name} must not contain duplicates"
        )
    return normalized


def _status(value: Any) -> GenerationStatus:
    """Parse the closed terminal-status vocabulary without coercion."""
    if type(value) is GenerationStatus:
        return value
    if type(value) is not str:
        raise DynamicItemGenerationError(
            "invalid_status", "status must be a GenerationStatus or exact string"
        )
    try:
        return GenerationStatus(value)
    except ValueError as exc:
        raise DynamicItemGenerationError(
            "invalid_status", "status must be generated, abstained, or failed"
        ) from exc


def _sha256(value: Any, field_name: str) -> str:
    """Validate one complete lowercase SHA-256 digest."""
    if type(value) is not str:
        raise DynamicItemGenerationError(
            "invalid_sha256", f"{field_name} must be a string"
        )
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise DynamicItemGenerationError(
            "invalid_sha256",
            f"{field_name} must be a complete lowercase SHA-256 digest",
        )
    return value


def _criterion_set(value: Any) -> CriterionSetExecutionBinding:
    """Parse one criterion set and translate its errors into this ACL."""
    try:
        return CriterionSetExecutionBinding.from_mapping(value)
    except EvaluationCriterionBindingError as exc:
        raise DynamicItemGenerationError(exc.code, str(exc)) from exc


@dataclass(frozen=True)
class GenerationConfigurationIdentity:
    """Exact reusable identity of one human, model, or algorithmic generator."""

    generator_family_ref: str
    provider_ref: str
    model_revision_ref: str
    implementation_revision_ref: str
    instruction_revision_ref: str
    response_schema_revision_ref: str
    workflow_mode_ref: str
    modality_channel_ref: str

    def __post_init__(self) -> None:
        """Retain an exact configuration identity without alias normalization."""
        for field_name in _CONFIGURATION_FIELDS:
            object.__setattr__(
                self, field_name, _reference(getattr(self, field_name), field_name)
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "GenerationConfigurationIdentity":
        """Translate untrusted configuration data into the exact domain value."""
        payload = _mapping(value, "configuration")
        _reject_unknown_fields(payload, _CONFIGURATION_FIELDS, "configuration")
        missing = _CONFIGURATION_FIELDS - set(payload)
        if missing:
            raise DynamicItemGenerationError(
                "missing_field",
                f"configuration is missing required fields: {sorted(missing)}",
            )
        return cls(
            **{field_name: payload[field_name] for field_name in _CONFIGURATION_FIELDS}
        )

    def to_payload(self) -> dict[str, str]:
        """Return the provider-neutral configuration representation."""
        return {
            "generator_family_ref": self.generator_family_ref,
            "provider_ref": self.provider_ref,
            "model_revision_ref": self.model_revision_ref,
            "implementation_revision_ref": self.implementation_revision_ref,
            "instruction_revision_ref": self.instruction_revision_ref,
            "response_schema_revision_ref": self.response_schema_revision_ref,
            "workflow_mode_ref": self.workflow_mode_ref,
            "modality_channel_ref": self.modality_channel_ref,
        }


@dataclass(frozen=True)
class DynamicItemGenerationInvocation:
    """Immutable evidence for one generator execution under frozen criteria."""

    invocation_ref: str
    configuration: GenerationConfigurationIdentity
    blueprint_revision_ref: str
    criterion_set: CriterionSetExecutionBinding
    target_criterion_refs: tuple[str, ...] | list[str]
    source_snapshot_refs: tuple[str, ...] | list[str]
    retrieval_context_refs: tuple[str, ...] | list[str]
    attempt_refs: tuple[str, ...] | list[str]
    seed_ref: str | None
    status: GenerationStatus | str
    generated_item_ref: str | None
    generated_content_ref: str | None
    generated_content_sha256: str | None
    reason_ref: str | None
    contract_id: str = DYNAMIC_ITEM_GENERATION_CONTRACT_V1

    def __post_init__(self) -> None:
        """Enforce criterion, provenance, and terminal-state invariants."""
        if self.contract_id != DYNAMIC_ITEM_GENERATION_CONTRACT_V1:
            raise DynamicItemGenerationError(
                "contract_incompatible", "unsupported dynamic item-generation contract"
            )
        object.__setattr__(
            self, "invocation_ref", _reference(self.invocation_ref, "invocation_ref")
        )
        object.__setattr__(
            self,
            "blueprint_revision_ref",
            _reference(self.blueprint_revision_ref, "blueprint_revision_ref"),
        )
        if type(self.configuration) is not GenerationConfigurationIdentity:
            raise DynamicItemGenerationError(
                "invalid_configuration", "configuration has the wrong domain type"
            )
        if type(self.criterion_set) is not CriterionSetExecutionBinding:
            raise DynamicItemGenerationError(
                "invalid_criterion_set", "criterion_set has the wrong domain type"
            )
        if self.blueprint_revision_ref != self.criterion_set.blueprint_revision_ref:
            raise DynamicItemGenerationError(
                "criterion_set_blueprint_mismatch",
                "invocation blueprint must match the frozen criterion-set blueprint",
            )
        targets = _reference_tuple(
            self.target_criterion_refs,
            "target_criterion_refs",
            allow_empty=False,
            maximum=MAX_GENERATION_CRITERIA,
        )
        if targets != self.criterion_set.criterion_refs:
            raise DynamicItemGenerationError(
                "criterion_coverage_mismatch",
                "generation must target every frozen criterion exactly once in order",
            )
        object.__setattr__(self, "target_criterion_refs", targets)
        object.__setattr__(
            self,
            "source_snapshot_refs",
            _reference_tuple(
                self.source_snapshot_refs,
                "source_snapshot_refs",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "retrieval_context_refs",
            _reference_tuple(
                self.retrieval_context_refs,
                "retrieval_context_refs",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "attempt_refs",
            _reference_tuple(self.attempt_refs, "attempt_refs", allow_empty=False),
        )
        object.__setattr__(
            self, "seed_ref", _optional_reference(self.seed_ref, "seed_ref")
        )
        normalized_status = _status(self.status)
        object.__setattr__(self, "status", normalized_status)

        generated_item_ref = _optional_reference(
            self.generated_item_ref, "generated_item_ref"
        )
        generated_content_ref = _optional_reference(
            self.generated_content_ref, "generated_content_ref"
        )
        reason_ref = _optional_reference(self.reason_ref, "reason_ref")

        if normalized_status is GenerationStatus.GENERATED:
            if (
                generated_item_ref is None
                or generated_content_ref is None
                or self.generated_content_sha256 is None
            ):
                raise DynamicItemGenerationError(
                    "generated_content_incomplete",
                    "generated status requires item, content, and complete digest identity",
                )
            content_sha256 = _sha256(
                self.generated_content_sha256, "generated_content_sha256"
            )
            if reason_ref is not None:
                raise DynamicItemGenerationError(
                    "generated_has_reason",
                    "generated status must not carry a failure reason",
                )
        else:
            if (
                generated_item_ref is not None
                or generated_content_ref is not None
                or self.generated_content_sha256 is not None
            ):
                raise DynamicItemGenerationError(
                    "non_generated_has_content",
                    "failed and abstained invocations cannot manufacture generated content",
                )
            if reason_ref is None:
                raise DynamicItemGenerationError(
                    "non_generated_requires_reason",
                    "failed and abstained invocations require a reason reference",
                )
            content_sha256 = None

        object.__setattr__(self, "generated_item_ref", generated_item_ref)
        object.__setattr__(self, "generated_content_ref", generated_content_ref)
        object.__setattr__(self, "generated_content_sha256", content_sha256)
        object.__setattr__(self, "reason_ref", reason_ref)

    @classmethod
    def from_json(cls, value: str) -> "DynamicItemGenerationInvocation":
        """Decode provider-neutral JSON while rejecting duplicate members."""
        if type(value) is not str:
            raise DynamicItemGenerationError(
                "invalid_json", "generation invocation JSON must be a string"
            )
        if not _json_depth_is_bounded(value):
            raise DynamicItemGenerationError(
                "invalid_json", "generation invocation JSON exceeds the nesting limit"
            )
        try:
            payload = json.loads(value, object_pairs_hook=_unique_object)
        except DynamicItemGenerationError:
            raise
        except (ValueError, RecursionError) as exc:
            raise DynamicItemGenerationError(
                "invalid_json", "generation invocation JSON is invalid"
            ) from exc
        return cls.from_mapping(payload)

    @classmethod
    def from_mapping(cls, value: Any) -> "DynamicItemGenerationInvocation":
        """Apply the provider-facing Anti-Corruption Layer to one invocation."""
        payload = _mapping(value, "generation invocation")
        _reject_unknown_fields(payload, _INVOCATION_FIELDS, "generation invocation")
        missing = _INVOCATION_FIELDS - set(payload)
        if missing:
            raise DynamicItemGenerationError(
                "missing_field",
                f"generation invocation is missing required fields: {sorted(missing)}",
            )
        return cls(
            contract_id=payload["contract_id"],
            invocation_ref=payload["invocation_ref"],
            configuration=GenerationConfigurationIdentity.from_mapping(
                payload["configuration"]
            ),
            blueprint_revision_ref=payload["blueprint_revision_ref"],
            criterion_set=_criterion_set(payload["criterion_set"]),
            target_criterion_refs=payload["target_criterion_refs"],
            source_snapshot_refs=payload["source_snapshot_refs"],
            retrieval_context_refs=payload["retrieval_context_refs"],
            attempt_refs=payload["attempt_refs"],
            seed_ref=payload["seed_ref"],
            status=payload["status"],
            generated_item_ref=payload["generated_item_ref"],
            generated_content_ref=payload["generated_content_ref"],
            generated_content_sha256=payload["generated_content_sha256"],
            reason_ref=payload["reason_ref"],
        )

    def to_payload(self) -> dict[str, Any]:
        """Return a detached source-text-free provider-neutral envelope."""
        return {
            "contract_id": self.contract_id,
            "invocation_ref": self.invocation_ref,
            "configuration": self.configuration.to_payload(),
            "blueprint_revision_ref": self.blueprint_revision_ref,
            "criterion_set": self.criterion_set.to_payload(),
            "target_criterion_refs": list(self.target_criterion_refs),
            "source_snapshot_refs": list(self.source_snapshot_refs),
            "retrieval_context_refs": list(self.retrieval_context_refs),
            "attempt_refs": list(self.attempt_refs),
            "seed_ref": self.seed_ref,
            "status": self.status.value,
            "generated_item_ref": self.generated_item_ref,
            "generated_content_ref": self.generated_content_ref,
            "generated_content_sha256": self.generated_content_sha256,
            "reason_ref": self.reason_ref,
        }
