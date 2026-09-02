"""Immutable evaluation-criterion bindings for provider execution evidence.

The owning product or measurement registry authors criterion meaning. This
module admits only an exact, content-addressed snapshot of that meaning so a
provider invocation cannot evaluate unnamed, missing, or substituted criteria.
Raw customer evidence and provider credentials remain outside this contract.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field
from typing import Any

MAX_CRITERION_BINDING_REFERENCES = 128
MAX_CRITERION_BINDING_CATEGORIES = 64
MAX_CRITERION_BINDING_REFERENCE_LENGTH = 256

_CATEGORY_TOKEN = object()
_CRITERION_TOKEN = object()
_CRITERION_SET_TOKEN = object()

_CATEGORY_FIELDS = frozenset(
    {
        "definition_ref",
        "definition_sha256",
        "order_index",
    }
)
_CRITERION_FIELDS = frozenset(
    {
        "criterion_revision_ref",
        "definition_ref",
        "definition_sha256",
        "admissible_evidence_rule_ref",
        "admissible_evidence_rule_sha256",
        "exclusion_rule_ref",
        "exclusion_rule_sha256",
        "response_semantics_ref",
        "response_semantics_sha256",
        "abstention_rule_ref",
        "abstention_rule_sha256",
        "not_observable_rule_ref",
        "not_observable_rule_sha256",
        "categories",
    }
)
_SET_FIELDS = frozenset(
    {
        "criterion_set_snapshot_ref",
        "criterion_set_sha256",
        "blueprint_revision_ref",
        "rubric_revision_ref",
        "intended_use_ref",
        "construct_ref",
        "population_scope_ref",
        "language_scope_ref",
        "domain_scope_ref",
        "criteria",
    }
)


class EvaluationCriterionBindingError(ValueError):
    """Stable fail-closed error for criterion-binding violations."""

    def __init__(self, code: str, message: str) -> None:
        """Retain a bounded machine-readable rejection code."""
        self.code = code
        super().__init__(message)


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    """Require one exact string-keyed mapping at an ACL boundary."""
    if type(value) is not dict:
        raise EvaluationCriterionBindingError(
            "invalid_object", f"{field_name} must be an exact object"
        )
    if any(type(key) is not str for key in value):
        raise EvaluationCriterionBindingError(
            "invalid_object_key", f"{field_name} keys must be strings"
        )
    return value


def _reject_unknown_fields(
    payload: Mapping[str, Any],
    allowed: frozenset[str],
    field_name: str,
) -> None:
    """Reject fields that are not part of the closed criterion contract."""
    unknown = set(payload) - allowed
    if unknown:
        raise EvaluationCriterionBindingError(
            "unknown_field",
            f"{field_name} contains unsupported fields: {sorted(unknown)}",
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
            unicodedata.category(character) in {"Cc", "Cs"} for character in value
        )
    ):
        raise EvaluationCriterionBindingError(
            "invalid_reference",
            f"{field_name} must be an exact bounded opaque reference",
        )
    return value


def _sha256(value: Any, field_name: str) -> str:
    """Validate one complete lowercase SHA-256 digest."""
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


def _positive_index(value: Any, field_name: str) -> int:
    """Validate a non-negative exact integer category order."""
    if type(value) is not int or value < 0:
        raise EvaluationCriterionBindingError(
            "invalid_order_index",
            f"{field_name} must be a non-negative integer",
        )
    return value


def _fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash one canonical JSON-compatible immutable domain payload."""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class CategoryExecutionBinding:
    """Content-addressed meaning of one admissible response category."""

    category_ref: str
    definition_ref: str
    definition_sha256: str
    order_index: int
    _admission_token: InitVar[object | None] = None
    _integrity_sha256: str = field(init=False, repr=False, compare=False)

    def __post_init__(self, _admission_token: object | None) -> None:
        """Seal direct construction and record the admitted fingerprint."""
        if _admission_token is not _CATEGORY_TOKEN:
            raise ValueError(
                "CategoryExecutionBinding must be created by from_mapping"
            )
        object.__setattr__(
            self,
            "_integrity_sha256",
            _fingerprint(self._payload_with_identity_unchecked()),
        )

    def _payload_unchecked(self) -> dict[str, Any]:
        """Return category meaning without its mapping-key identity."""
        return {
            "definition_ref": self.definition_ref,
            "definition_sha256": self.definition_sha256,
            "order_index": self.order_index,
        }

    def _payload_with_identity_unchecked(self) -> dict[str, Any]:
        """Return category meaning including the mapping-key identity."""
        return {"category_ref": self.category_ref, **self._payload_unchecked()}

    def _assert_integrity(self) -> None:
        """Reject object-level mutation after factory admission."""
        try:
            current = _fingerprint(self._payload_with_identity_unchecked())
        except (TypeError, ValueError, AttributeError) as exc:
            raise EvaluationCriterionBindingError(
                "category_binding_integrity_mismatch",
                "category binding changed after admission",
            ) from exc
        if current != self._integrity_sha256:
            raise EvaluationCriterionBindingError(
                "category_binding_integrity_mismatch",
                "category binding changed after admission",
            )

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        category_ref: str,
    ) -> "CategoryExecutionBinding":
        """Parse one category while retaining its canonical mapping key."""
        payload = _mapping(value, "category binding")
        _reject_unknown_fields(payload, _CATEGORY_FIELDS, "category binding")
        missing = _CATEGORY_FIELDS - set(payload)
        if missing:
            raise EvaluationCriterionBindingError(
                "missing_field",
                f"category binding is missing required fields: {sorted(missing)}",
            )
        return cls(
            category_ref=_reference(category_ref, "category_ref"),
            definition_ref=_reference(payload["definition_ref"], "definition_ref"),
            definition_sha256=_sha256(
                payload["definition_sha256"], "definition_sha256"
            ),
            order_index=_positive_index(payload["order_index"], "order_index"),
            _admission_token=_CATEGORY_TOKEN,
        )

    def to_payload(self) -> dict[str, Any]:
        """Return the source-text-free category meaning receipt."""
        self._assert_integrity()
        return self._payload_unchecked()


@dataclass(frozen=True, slots=True)
class CriterionExecutionBinding:
    """Exact substantive rules and categories for one evaluation criterion."""

    criterion_ref: str
    criterion_revision_ref: str
    definition_ref: str
    definition_sha256: str
    admissible_evidence_rule_ref: str
    admissible_evidence_rule_sha256: str
    exclusion_rule_ref: str
    exclusion_rule_sha256: str
    response_semantics_ref: str
    response_semantics_sha256: str
    abstention_rule_ref: str
    abstention_rule_sha256: str
    not_observable_rule_ref: str
    not_observable_rule_sha256: str
    categories: tuple[CategoryExecutionBinding, ...]
    _admission_token: InitVar[object | None] = None
    _integrity_sha256: str = field(init=False, repr=False, compare=False)

    def __post_init__(self, _admission_token: object | None) -> None:
        """Seal direct construction and record the admitted fingerprint."""
        if _admission_token is not _CRITERION_TOKEN:
            raise ValueError(
                "CriterionExecutionBinding must be created by from_mapping"
            )
        object.__setattr__(
            self,
            "_integrity_sha256",
            _fingerprint(self._payload_with_identity_unchecked()),
        )

    def _payload_unchecked(self) -> dict[str, Any]:
        """Return criterion meaning without its mapping-key identity."""
        return {
            "criterion_revision_ref": self.criterion_revision_ref,
            "definition_ref": self.definition_ref,
            "definition_sha256": self.definition_sha256,
            "admissible_evidence_rule_ref": self.admissible_evidence_rule_ref,
            "admissible_evidence_rule_sha256": (
                self.admissible_evidence_rule_sha256
            ),
            "exclusion_rule_ref": self.exclusion_rule_ref,
            "exclusion_rule_sha256": self.exclusion_rule_sha256,
            "response_semantics_ref": self.response_semantics_ref,
            "response_semantics_sha256": self.response_semantics_sha256,
            "abstention_rule_ref": self.abstention_rule_ref,
            "abstention_rule_sha256": self.abstention_rule_sha256,
            "not_observable_rule_ref": self.not_observable_rule_ref,
            "not_observable_rule_sha256": self.not_observable_rule_sha256,
            "categories": {
                category.category_ref: category._payload_unchecked()
                for category in self.categories
            },
        }

    def _payload_with_identity_unchecked(self) -> dict[str, Any]:
        """Return criterion meaning including the mapping-key identity."""
        return {"criterion_ref": self.criterion_ref, **self._payload_unchecked()}

    def _assert_integrity(self) -> None:
        """Reject child or object mutation after factory admission."""
        try:
            if type(self.categories) is not tuple or any(
                type(category) is not CategoryExecutionBinding
                for category in self.categories
            ):
                raise TypeError("criterion categories have the wrong domain type")
            for category in self.categories:
                category._assert_integrity()
            current = _fingerprint(self._payload_with_identity_unchecked())
        except (
            EvaluationCriterionBindingError,
            TypeError,
            ValueError,
            AttributeError,
        ) as exc:
            raise EvaluationCriterionBindingError(
                "criterion_binding_integrity_mismatch",
                "criterion binding changed after admission",
            ) from exc
        if current != self._integrity_sha256:
            raise EvaluationCriterionBindingError(
                "criterion_binding_integrity_mismatch",
                "criterion binding changed after admission",
            )

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        criterion_ref: str,
    ) -> "CriterionExecutionBinding":
        """Parse one criterion and require all decision-relevant meaning."""
        payload = _mapping(value, "criterion binding")
        _reject_unknown_fields(payload, _CRITERION_FIELDS, "criterion binding")
        missing = _CRITERION_FIELDS - set(payload)
        if missing:
            raise EvaluationCriterionBindingError(
                "missing_field",
                f"criterion binding is missing required fields: {sorted(missing)}",
            )
        raw_categories = _mapping(payload["categories"], "criterion categories")
        if not 2 <= len(raw_categories) <= MAX_CRITERION_BINDING_CATEGORIES:
            raise EvaluationCriterionBindingError(
                "invalid_category_set",
                "criterion categories must contain 2..64 definitions",
            )
        categories = tuple(
            CategoryExecutionBinding.from_mapping(item, category_ref=category_key)
            for category_key, item in raw_categories.items()
        )
        order_indices = tuple(category.order_index for category in categories)
        if len(set(order_indices)) != len(order_indices):
            raise EvaluationCriterionBindingError(
                "duplicate_order_index",
                "criterion category order indexes must be unique",
            )
        if set(order_indices) != set(range(len(categories))):
            raise EvaluationCriterionBindingError(
                "non_contiguous_order_index",
                "criterion category order indexes must be contiguous from zero",
            )
        ordered_categories = tuple(
            sorted(categories, key=lambda item: item.order_index)
        )
        return cls(
            criterion_ref=_reference(criterion_ref, "criterion_ref"),
            criterion_revision_ref=_reference(
                payload["criterion_revision_ref"], "criterion_revision_ref"
            ),
            definition_ref=_reference(payload["definition_ref"], "definition_ref"),
            definition_sha256=_sha256(
                payload["definition_sha256"], "definition_sha256"
            ),
            admissible_evidence_rule_ref=_reference(
                payload["admissible_evidence_rule_ref"],
                "admissible_evidence_rule_ref",
            ),
            admissible_evidence_rule_sha256=_sha256(
                payload["admissible_evidence_rule_sha256"],
                "admissible_evidence_rule_sha256",
            ),
            exclusion_rule_ref=_reference(
                payload["exclusion_rule_ref"], "exclusion_rule_ref"
            ),
            exclusion_rule_sha256=_sha256(
                payload["exclusion_rule_sha256"], "exclusion_rule_sha256"
            ),
            response_semantics_ref=_reference(
                payload["response_semantics_ref"], "response_semantics_ref"
            ),
            response_semantics_sha256=_sha256(
                payload["response_semantics_sha256"],
                "response_semantics_sha256",
            ),
            abstention_rule_ref=_reference(
                payload["abstention_rule_ref"], "abstention_rule_ref"
            ),
            abstention_rule_sha256=_sha256(
                payload["abstention_rule_sha256"], "abstention_rule_sha256"
            ),
            not_observable_rule_ref=_reference(
                payload["not_observable_rule_ref"], "not_observable_rule_ref"
            ),
            not_observable_rule_sha256=_sha256(
                payload["not_observable_rule_sha256"],
                "not_observable_rule_sha256",
            ),
            categories=ordered_categories,
            _admission_token=_CRITERION_TOKEN,
        )

    @property
    def category_refs(self) -> tuple[str, ...]:
        """Return categories in the governed response order."""
        self._assert_integrity()
        return tuple(category.category_ref for category in self.categories)

    def to_payload(self) -> dict[str, Any]:
        """Return the source-text-free criterion meaning receipt."""
        self._assert_integrity()
        return self._payload_unchecked()


@dataclass(frozen=True, slots=True)
class CriterionSetExecutionBinding:
    """Immutable criterion-set meaning bound to one blueprint and rubric."""

    criterion_set_snapshot_ref: str
    criterion_set_sha256: str
    blueprint_revision_ref: str
    rubric_revision_ref: str
    intended_use_ref: str
    construct_ref: str
    population_scope_ref: str
    language_scope_ref: str
    domain_scope_ref: str
    criteria: tuple[CriterionExecutionBinding, ...]
    _admission_token: InitVar[object | None] = None
    _integrity_sha256: str = field(init=False, repr=False, compare=False)

    def __post_init__(self, _admission_token: object | None) -> None:
        """Seal direct construction and record the admitted content digest."""
        if _admission_token is not _CRITERION_SET_TOKEN:
            raise ValueError(
                "CriterionSetExecutionBinding must be created by from_mapping"
            )
        object.__setattr__(self, "_integrity_sha256", self.criterion_set_sha256)

    def _content_payload_unchecked(self) -> dict[str, Any]:
        """Return all content-addressed fields except the digest itself."""
        return {
            "criterion_set_snapshot_ref": self.criterion_set_snapshot_ref,
            "blueprint_revision_ref": self.blueprint_revision_ref,
            "rubric_revision_ref": self.rubric_revision_ref,
            "intended_use_ref": self.intended_use_ref,
            "construct_ref": self.construct_ref,
            "population_scope_ref": self.population_scope_ref,
            "language_scope_ref": self.language_scope_ref,
            "domain_scope_ref": self.domain_scope_ref,
            "criteria": {
                criterion.criterion_ref: criterion._payload_unchecked()
                for criterion in self.criteria
            },
        }

    def _assert_integrity(self) -> None:
        """Reject child, collection, or field mutation after admission."""
        try:
            if type(self.criteria) is not tuple or any(
                type(criterion) is not CriterionExecutionBinding
                for criterion in self.criteria
            ):
                raise TypeError("criterion set contains a foreign domain value")
            for criterion in self.criteria:
                criterion._assert_integrity()
            current = _fingerprint(self._content_payload_unchecked())
        except (
            EvaluationCriterionBindingError,
            TypeError,
            ValueError,
            AttributeError,
        ) as exc:
            raise EvaluationCriterionBindingError(
                "criterion_set_integrity_mismatch",
                "criterion set changed after admission",
            ) from exc
        if (
            current != self._integrity_sha256
            or current != self.criterion_set_sha256
        ):
            raise EvaluationCriterionBindingError(
                "criterion_set_integrity_mismatch",
                "criterion set changed after admission",
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "CriterionSetExecutionBinding":
        """Parse and verify a complete non-empty criterion-set binding."""
        payload = _mapping(value, "criterion set binding")
        _reject_unknown_fields(payload, _SET_FIELDS, "criterion set binding")
        missing = _SET_FIELDS - set(payload)
        if missing:
            raise EvaluationCriterionBindingError(
                "missing_field",
                f"criterion set binding is missing required fields: {sorted(missing)}",
            )
        raw_criteria = _mapping(payload["criteria"], "criterion set criteria")
        if not raw_criteria or len(raw_criteria) > MAX_CRITERION_BINDING_REFERENCES:
            raise EvaluationCriterionBindingError(
                "invalid_criterion_set",
                "criterion set must contain 1..128 definitions",
            )
        criteria = tuple(
            CriterionExecutionBinding.from_mapping(item, criterion_ref=criterion_key)
            for criterion_key, item in raw_criteria.items()
        )
        ordered_criteria = tuple(
            sorted(criteria, key=lambda item: item.criterion_ref)
        )
        revision_refs = tuple(
            item.criterion_revision_ref for item in ordered_criteria
        )
        if len(set(revision_refs)) != len(revision_refs):
            raise EvaluationCriterionBindingError(
                "duplicate_criterion_revision",
                "criterion revision identities must be unique",
            )
        normalized = cls(
            criterion_set_snapshot_ref=_reference(
                payload["criterion_set_snapshot_ref"], "criterion_set_snapshot_ref"
            ),
            criterion_set_sha256=_sha256(
                payload["criterion_set_sha256"], "criterion_set_sha256"
            ),
            blueprint_revision_ref=_reference(
                payload["blueprint_revision_ref"], "blueprint_revision_ref"
            ),
            rubric_revision_ref=_reference(
                payload["rubric_revision_ref"], "rubric_revision_ref"
            ),
            intended_use_ref=_reference(
                payload["intended_use_ref"], "intended_use_ref"
            ),
            construct_ref=_reference(payload["construct_ref"], "construct_ref"),
            population_scope_ref=_reference(
                payload["population_scope_ref"], "population_scope_ref"
            ),
            language_scope_ref=_reference(
                payload["language_scope_ref"], "language_scope_ref"
            ),
            domain_scope_ref=_reference(
                payload["domain_scope_ref"], "domain_scope_ref"
            ),
            criteria=ordered_criteria,
            _admission_token=_CRITERION_SET_TOKEN,
        )
        computed = _fingerprint(normalized._content_payload_unchecked())
        if computed != normalized.criterion_set_sha256:
            raise EvaluationCriterionBindingError(
                "criterion_set_digest_mismatch",
                "criterion_set_sha256 does not identify the admitted criterion content",
            )
        object.__setattr__(normalized, "_integrity_sha256", computed)
        return normalized

    @property
    def criterion_refs(self) -> tuple[str, ...]:
        """Return criterion identities in deterministic snapshot order."""
        self._assert_integrity()
        return tuple(criterion.criterion_ref for criterion in self.criteria)

    def criterion(self, criterion_ref: str) -> CriterionExecutionBinding:
        """Return one registered criterion or fail with a stable error."""
        self._assert_integrity()
        normalized_ref = _reference(criterion_ref, "criterion_ref")
        for criterion in self.criteria:
            if criterion.criterion_ref == normalized_ref:
                return criterion
        raise EvaluationCriterionBindingError(
            "criterion_not_registered",
            "criterion is not present in the frozen criterion set",
        )

    def to_payload(self) -> dict[str, Any]:
        """Return the exact detached criterion-set meaning receipt."""
        self._assert_integrity()
        content = self._content_payload_unchecked()
        return {
            "criterion_set_snapshot_ref": content["criterion_set_snapshot_ref"],
            "criterion_set_sha256": self.criterion_set_sha256,
            "blueprint_revision_ref": content["blueprint_revision_ref"],
            "rubric_revision_ref": content["rubric_revision_ref"],
            "intended_use_ref": content["intended_use_ref"],
            "construct_ref": content["construct_ref"],
            "population_scope_ref": content["population_scope_ref"],
            "language_scope_ref": content["language_scope_ref"],
            "domain_scope_ref": content["domain_scope_ref"],
            "criteria": content["criteria"],
        }
