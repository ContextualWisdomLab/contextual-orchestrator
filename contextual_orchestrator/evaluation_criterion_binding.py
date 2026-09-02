"""Source-text-free bindings to immutable evaluation criterion snapshots.

The module does not own criterion meaning. It carries exact identities, SHA-256
digests, and admissible response-category references so provider-facing code can
prove which externally governed criteria were administered and reject invented
criteria or categories.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MAX_CRITERION_BINDING_REFERENCE_LENGTH = 256
MAX_CRITERION_BINDINGS = 128
MAX_CATEGORY_BINDINGS = 64

_CRITERION_FIELDS = frozenset(
    {"criterion_revision_ref", "criterion_sha256", "category_refs"}
)
_CRITERION_SET_FIELDS = frozenset(
    {
        "criterion_set_snapshot_ref",
        "criterion_set_sha256",
        "blueprint_revision_ref",
        "rubric_revision_ref",
        "criteria",
    }
)


class EvaluationCriterionBindingError(ValueError):
    """Stable fail-closed error for criterion-binding contract violations."""

    def __init__(self, code: str, message: str) -> None:
        """Retain one bounded machine-readable rejection code."""
        self.code = code
        super().__init__(message)


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    """Require an object with exact string member names."""
    if not isinstance(value, Mapping):
        raise EvaluationCriterionBindingError(
            "invalid_object", f"{field_name} must be an object"
        )
    if any(type(key) is not str for key in value):
        raise EvaluationCriterionBindingError(
            "invalid_object_key", f"{field_name} keys must be strings"
        )
    return value


def _fields(
    value: Mapping[str, Any], allowed: frozenset[str], field_name: str
) -> None:
    """Reject missing and unknown object members at the boundary."""
    unknown = set(value) - allowed
    if unknown:
        raise EvaluationCriterionBindingError(
            "unknown_field",
            f"{field_name} contains unsupported fields: {sorted(unknown)}",
        )
    missing = allowed - set(value)
    if missing:
        raise EvaluationCriterionBindingError(
            "missing_field",
            f"{field_name} is missing required fields: {sorted(missing)}",
        )


def _reference(value: Any, field_name: str) -> str:
    """Validate one exact bounded opaque reference without normalization."""
    if type(value) is not str:
        raise EvaluationCriterionBindingError(
            "invalid_reference", f"{field_name} must be a string"
        )
    if (
        not value
        or value != value.strip()
        or value.startswith("\ufeff")
        or value.endswith("\ufeff")
        or len(value) > MAX_CRITERION_BINDING_REFERENCE_LENGTH
        or any(
            unicodedata.category(character) in {"Cc", "Cs"}
            for character in value
        )
    ):
        raise EvaluationCriterionBindingError(
            "invalid_reference",
            f"{field_name} must be an exact bounded opaque reference",
        )
    return value


def _sha256(value: Any, field_name: str) -> str:
    """Validate one complete lowercase hexadecimal SHA-256 digest."""
    if type(value) is not str:
        raise EvaluationCriterionBindingError(
            "invalid_sha256", f"{field_name} must be a string"
        )
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise EvaluationCriterionBindingError(
            "invalid_sha256",
            f"{field_name} must be a complete lowercase SHA-256 digest",
        )
    return value


def _references(value: Any, field_name: str) -> tuple[str, ...]:
    """Validate a non-empty bounded unique reference collection."""
    if not isinstance(value, (list, tuple)):
        raise EvaluationCriterionBindingError(
            "invalid_references", f"{field_name} must be an array"
        )
    if not value or len(value) > MAX_CATEGORY_BINDINGS:
        raise EvaluationCriterionBindingError(
            "invalid_references",
            f"{field_name} must contain 1..{MAX_CATEGORY_BINDINGS} references",
        )
    normalized = tuple(_reference(item, field_name) for item in value)
    if len(set(normalized)) != len(normalized):
        raise EvaluationCriterionBindingError(
            "duplicate_reference", f"{field_name} must not contain duplicates"
        )
    return normalized


@dataclass(frozen=True)
class CriterionExecutionBinding:
    """Exact executable identity of one externally governed criterion."""

    criterion_ref: str
    criterion_revision_ref: str
    criterion_sha256: str
    category_refs: tuple[str, ...] | list[str]

    def __post_init__(self) -> None:
        """Copy caller collections and validate criterion identity and categories."""
        object.__setattr__(
            self, "criterion_ref", _reference(self.criterion_ref, "criterion_ref")
        )
        object.__setattr__(
            self,
            "criterion_revision_ref",
            _reference(self.criterion_revision_ref, "criterion_revision_ref"),
        )
        object.__setattr__(
            self,
            "criterion_sha256",
            _sha256(self.criterion_sha256, "criterion_sha256"),
        )
        object.__setattr__(
            self,
            "category_refs",
            _references(self.category_refs, "category_refs"),
        )

    @classmethod
    def from_mapping(
        cls, value: Any, *, criterion_ref: str
    ) -> "CriterionExecutionBinding":
        """Parse one criterion value from an untrusted keyed object member."""
        payload = _mapping(value, "criterion binding")
        _fields(payload, _CRITERION_FIELDS, "criterion binding")
        return cls(
            criterion_ref=criterion_ref,
            criterion_revision_ref=payload["criterion_revision_ref"],
            criterion_sha256=payload["criterion_sha256"],
            category_refs=payload["category_refs"],
        )

    def to_payload(self) -> dict[str, Any]:
        """Return the source-text-free executable criterion representation."""
        return {
            "criterion_revision_ref": self.criterion_revision_ref,
            "criterion_sha256": self.criterion_sha256,
            "category_refs": list(self.category_refs),
        }


@dataclass(frozen=True)
class CriterionSetExecutionBinding:
    """Exact criterion-set identity supplied to generator and rater executions."""

    criterion_set_snapshot_ref: str
    criterion_set_sha256: str
    blueprint_revision_ref: str
    rubric_revision_ref: str
    criteria: tuple[CriterionExecutionBinding, ...] | list[CriterionExecutionBinding]

    def __post_init__(self) -> None:
        """Validate the set identity and copy a deterministic criterion ordering."""
        object.__setattr__(
            self,
            "criterion_set_snapshot_ref",
            _reference(
                self.criterion_set_snapshot_ref, "criterion_set_snapshot_ref"
            ),
        )
        object.__setattr__(
            self,
            "criterion_set_sha256",
            _sha256(self.criterion_set_sha256, "criterion_set_sha256"),
        )
        object.__setattr__(
            self,
            "blueprint_revision_ref",
            _reference(self.blueprint_revision_ref, "blueprint_revision_ref"),
        )
        object.__setattr__(
            self,
            "rubric_revision_ref",
            _reference(self.rubric_revision_ref, "rubric_revision_ref"),
        )
        if not isinstance(self.criteria, (list, tuple)):
            raise EvaluationCriterionBindingError(
                "invalid_criterion_set", "criteria must be an object-derived array"
            )
        if not self.criteria or len(self.criteria) > MAX_CRITERION_BINDINGS:
            raise EvaluationCriterionBindingError(
                "invalid_criterion_set",
                f"criteria must contain 1..{MAX_CRITERION_BINDINGS} definitions",
            )
        normalized = tuple(self.criteria)
        if any(type(item) is not CriterionExecutionBinding for item in normalized):
            raise EvaluationCriterionBindingError(
                "invalid_criterion",
                "criteria must contain exact CriterionExecutionBinding values",
            )
        ordered = tuple(sorted(normalized, key=lambda item: item.criterion_ref))
        refs = [item.criterion_ref for item in ordered]
        if len(set(refs)) != len(refs):
            raise EvaluationCriterionBindingError(
                "duplicate_criterion", "criterion identities must be unique"
            )
        object.__setattr__(self, "criteria", ordered)

    @classmethod
    def from_mapping(cls, value: Any) -> "CriterionSetExecutionBinding":
        """Parse one exact criterion-set snapshot from an untrusted object."""
        payload = _mapping(value, "criterion set")
        _fields(payload, _CRITERION_SET_FIELDS, "criterion set")
        criteria_payload = _mapping(payload["criteria"], "criteria")
        if not criteria_payload or len(criteria_payload) > MAX_CRITERION_BINDINGS:
            raise EvaluationCriterionBindingError(
                "invalid_criterion_set",
                f"criteria must contain 1..{MAX_CRITERION_BINDINGS} definitions",
            )
        return cls(
            criterion_set_snapshot_ref=payload["criterion_set_snapshot_ref"],
            criterion_set_sha256=payload["criterion_set_sha256"],
            blueprint_revision_ref=payload["blueprint_revision_ref"],
            rubric_revision_ref=payload["rubric_revision_ref"],
            criteria=tuple(
                CriterionExecutionBinding.from_mapping(
                    criterion_payload, criterion_ref=criterion_ref
                )
                for criterion_ref, criterion_payload in criteria_payload.items()
            ),
        )

    @property
    def criterion_refs(self) -> tuple[str, ...]:
        """Return every criterion identity in deterministic order."""
        return tuple(item.criterion_ref for item in self.criteria)

    def criterion_for(self, criterion_ref: str) -> CriterionExecutionBinding:
        """Return the exact binding for one registered criterion."""
        normalized_ref = _reference(criterion_ref, "criterion_ref")
        for criterion in self.criteria:
            if criterion.criterion_ref == normalized_ref:
                return criterion
        raise EvaluationCriterionBindingError(
            "criterion_not_registered", "criterion is not present in this set"
        )

    def to_payload(self) -> dict[str, Any]:
        """Return the exact source-text-free criterion-set binding."""
        return {
            "criterion_set_snapshot_ref": self.criterion_set_snapshot_ref,
            "criterion_set_sha256": self.criterion_set_sha256,
            "blueprint_revision_ref": self.blueprint_revision_ref,
            "rubric_revision_ref": self.rubric_revision_ref,
            "criteria": {
                item.criterion_ref: item.to_payload() for item in self.criteria
            },
        }
