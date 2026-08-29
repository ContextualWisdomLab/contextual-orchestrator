"""Domain-neutral governed rater observation bounded context.

The module is an Anti-Corruption Layer between provider-specific structured
outputs and the published language owned by ``fast-mlsirm``.  It preserves
criterion observations, abstentions, uncertainty, review signals, and opaque
evidence references while structurally rejecting scores and decisions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


GOVERNED_RATER_OBSERVATION_CONTRACT_V1 = "cwl_governed_rater_observation/v1"
MAX_RATER_REFERENCE_LENGTH = 256
MAX_RATER_OBSERVATIONS = 128
MAX_RATER_EVIDENCE_REFERENCES = 64
MAX_RATER_REVIEW_SIGNALS = 32

_PROHIBITED_DECISION_FIELDS = frozenset(
    {
        "score",
        "final_score",
        "latent_trait",
        "level",
        "placement",
        "pass_fail",
        "certification",
        "employment_decision",
    }
)
_CONFIGURATION_FIELDS = frozenset(
    {
        "rater_family_ref",
        "provider_ref",
        "implementation_revision_ref",
        "instruction_revision_ref",
        "response_schema_revision_ref",
        "workflow_mode_ref",
        "modality_channel_ref",
    }
)
_OBSERVATION_FIELDS = frozenset(
    {
        "criterion_ref",
        "status",
        "category_anchor_ref",
        "evidence_reference_ids",
        "uncertainty",
        "review_signal_refs",
        "reason_ref",
    }
)
_INVOCATION_FIELDS = frozenset(
    {
        "contract_id",
        "invocation_ref",
        "configuration",
        "task_revision_ref",
        "rubric_revision_ref",
        "response_evidence_ref",
        "observations",
    }
)


class RaterObservationError(ValueError):
    """Raised when data cannot cross the governed observation boundary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RaterObservationError("invalid_object", f"{field_name} must be an object")
    if any(type(key) is not str for key in value):
        raise RaterObservationError(
            "invalid_object_key", f"{field_name} keys must be strings"
        )
    return value


def _reference(value: Any, field_name: str) -> str:
    if type(value) is not str:
        raise RaterObservationError(
            "invalid_reference", f"{field_name} must be a string"
        )
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_RATER_REFERENCE_LENGTH:
        raise RaterObservationError(
            "invalid_reference",
            f"{field_name} must be a bounded non-empty reference",
        )
    if any(character.iscontrol() for character in normalized):
        raise RaterObservationError(
            "invalid_reference", f"{field_name} must not contain control characters"
        )
    return normalized


def _reference_tuple(
    value: Any,
    field_name: str,
    *,
    maximum: int,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise RaterObservationError(
            "invalid_references", f"{field_name} must be an array"
        )
    if (not allow_empty and not value) or len(value) > maximum:
        lower_bound = 0 if allow_empty else 1
        raise RaterObservationError(
            "invalid_references",
            f"{field_name} must contain {lower_bound}..{maximum} references",
        )
    normalized = tuple(_reference(item, field_name) for item in value)
    if len(set(normalized)) != len(normalized):
        raise RaterObservationError(
            "duplicate_reference", f"{field_name} must not contain duplicates"
        )
    return normalized


def _reject_unknown_fields(
    payload: Mapping[str, Any], allowed: frozenset[str], field_name: str
) -> None:
    unknown = set(payload) - allowed
    if unknown.intersection(_PROHIBITED_DECISION_FIELDS):
        raise RaterObservationError(
            "decision_leakage",
            f"{field_name} must not contain score or decision fields",
        )
    if unknown:
        raise RaterObservationError(
            "unknown_field",
            f"{field_name} contains unsupported fields: {sorted(unknown)}",
        )


@dataclass(frozen=True)
class RaterConfigurationIdentity:
    """Exact reusable identity of a human, model, or algorithmic rater."""

    rater_family_ref: str
    provider_ref: str
    implementation_revision_ref: str
    instruction_revision_ref: str
    response_schema_revision_ref: str
    workflow_mode_ref: str
    modality_channel_ref: str

    def __post_init__(self) -> None:
        for field_name in _CONFIGURATION_FIELDS:
            object.__setattr__(
                self, field_name, _reference(getattr(self, field_name), field_name)
            )

    @classmethod
    def from_mapping(cls, value: Any) -> RaterConfigurationIdentity:
        """Translate provider-neutral configuration data into the domain value object."""
        payload = _mapping(value, "configuration")
        _reject_unknown_fields(payload, _CONFIGURATION_FIELDS, "configuration")
        missing = _CONFIGURATION_FIELDS - set(payload)
        if missing:
            raise RaterObservationError(
                "missing_field",
                f"configuration is missing required fields: {sorted(missing)}",
            )
        return cls(**{field_name: payload[field_name] for field_name in _CONFIGURATION_FIELDS})

    def to_payload(self) -> dict[str, str]:
        """Return the published-language representation."""
        return {
            "rater_family_ref": self.rater_family_ref,
            "provider_ref": self.provider_ref,
            "implementation_revision_ref": self.implementation_revision_ref,
            "instruction_revision_ref": self.instruction_revision_ref,
            "response_schema_revision_ref": self.response_schema_revision_ref,
            "workflow_mode_ref": self.workflow_mode_ref,
            "modality_channel_ref": self.modality_channel_ref,
        }


@dataclass(frozen=True)
class CriterionObservation:
    """One criterion observation or explicit abstention from one invocation."""

    criterion_ref: str
    status: str
    category_anchor_ref: str | None
    evidence_reference_ids: tuple[str, ...]
    uncertainty: str
    review_signal_refs: tuple[str, ...]
    reason_ref: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "criterion_ref", _reference(self.criterion_ref, "criterion_ref"))
        if self.status not in {"observed", "abstained"}:
            raise RaterObservationError(
                "invalid_status", "status must be observed or abstained"
            )
        if self.uncertainty not in {"low", "medium", "high"}:
            raise RaterObservationError(
                "invalid_uncertainty", "uncertainty must be low, medium, or high"
            )
        evidence = _reference_tuple(
            self.evidence_reference_ids,
            "evidence_reference_ids",
            maximum=MAX_RATER_EVIDENCE_REFERENCES,
            allow_empty=self.status == "abstained",
        )
        signals = _reference_tuple(
            self.review_signal_refs,
            "review_signal_refs",
            maximum=MAX_RATER_REVIEW_SIGNALS,
            allow_empty=True,
        )
        object.__setattr__(self, "evidence_reference_ids", evidence)
        object.__setattr__(self, "review_signal_refs", signals)
        if self.status == "observed":
            object.__setattr__(
                self,
                "category_anchor_ref",
                _reference(self.category_anchor_ref, "category_anchor_ref"),
            )
            if self.reason_ref is not None:
                raise RaterObservationError(
                    "invalid_observed_state", "observed criteria must not have a reason_ref"
                )
        else:
            if self.category_anchor_ref is not None or evidence:
                raise RaterObservationError(
                    "invalid_abstention_state",
                    "abstentions must not contain a category or evidence",
                )
            object.__setattr__(self, "reason_ref", _reference(self.reason_ref, "reason_ref"))

    @classmethod
    def from_mapping(cls, value: Any) -> CriterionObservation:
        """Translate one untrusted structured observation into the domain entity."""
        payload = _mapping(value, "observation")
        _reject_unknown_fields(payload, _OBSERVATION_FIELDS, "observation")
        missing = _OBSERVATION_FIELDS - set(payload)
        if missing:
            raise RaterObservationError(
                "missing_field",
                f"observation is missing required fields: {sorted(missing)}",
            )
        return cls(
            criterion_ref=payload["criterion_ref"],
            status=payload["status"],
            category_anchor_ref=payload["category_anchor_ref"],
            evidence_reference_ids=tuple(payload["evidence_reference_ids"])
            if isinstance(payload["evidence_reference_ids"], (list, tuple))
            else payload["evidence_reference_ids"],
            uncertainty=payload["uncertainty"],
            review_signal_refs=tuple(payload["review_signal_refs"])
            if isinstance(payload["review_signal_refs"], (list, tuple))
            else payload["review_signal_refs"],
            reason_ref=payload["reason_ref"],
        )

    def to_payload(self) -> dict[str, Any]:
        """Return the published-language representation."""
        return {
            "criterion_ref": self.criterion_ref,
            "status": self.status,
            "category_anchor_ref": self.category_anchor_ref,
            "evidence_reference_ids": list(self.evidence_reference_ids),
            "uncertainty": self.uncertainty,
            "review_signal_refs": list(self.review_signal_refs),
            "reason_ref": self.reason_ref,
        }


@dataclass(frozen=True)
class RaterInvocation:
    """Aggregate root for exactly one execution of one rater configuration."""

    invocation_ref: str
    configuration: RaterConfigurationIdentity
    task_revision_ref: str
    rubric_revision_ref: str
    response_evidence_ref: str
    observations: tuple[CriterionObservation, ...]
    contract_id: str = GOVERNED_RATER_OBSERVATION_CONTRACT_V1

    def __post_init__(self) -> None:
        if self.contract_id != GOVERNED_RATER_OBSERVATION_CONTRACT_V1:
            raise RaterObservationError(
                "contract_incompatible", "unsupported governed-rater contract"
            )
        for field_name in (
            "invocation_ref",
            "task_revision_ref",
            "rubric_revision_ref",
            "response_evidence_ref",
        ):
            object.__setattr__(
                self, field_name, _reference(getattr(self, field_name), field_name)
            )
        if type(self.configuration) is not RaterConfigurationIdentity:
            raise RaterObservationError(
                "invalid_configuration", "configuration has the wrong domain type"
            )
        observations = tuple(self.observations)
        if not observations or len(observations) > MAX_RATER_OBSERVATIONS:
            raise RaterObservationError(
                "invalid_observations",
                f"observations must contain 1..{MAX_RATER_OBSERVATIONS} criteria",
            )
        if any(type(item) is not CriterionObservation for item in observations):
            raise RaterObservationError(
                "invalid_observation", "observations contain the wrong domain type"
            )
        criterion_refs = [item.criterion_ref for item in observations]
        if len(set(criterion_refs)) != len(criterion_refs):
            raise RaterObservationError(
                "duplicate_criterion", "an invocation has at most one observation per criterion"
            )
        object.__setattr__(self, "observations", observations)

    @classmethod
    def from_mapping(cls, value: Any) -> RaterInvocation:
        """Apply the Anti-Corruption Layer to an untrusted invocation envelope."""
        payload = _mapping(value, "invocation")
        _reject_unknown_fields(payload, _INVOCATION_FIELDS, "invocation")
        missing = _INVOCATION_FIELDS - set(payload)
        if missing:
            raise RaterObservationError(
                "missing_field",
                f"invocation is missing required fields: {sorted(missing)}",
            )
        raw_observations = payload["observations"]
        if not isinstance(raw_observations, Sequence) or isinstance(
            raw_observations, (str, bytes, bytearray)
        ):
            raise RaterObservationError(
                "invalid_observations", "observations must be an array"
            )
        return cls(
            contract_id=payload["contract_id"],
            invocation_ref=payload["invocation_ref"],
            configuration=RaterConfigurationIdentity.from_mapping(
                payload["configuration"]
            ),
            task_revision_ref=payload["task_revision_ref"],
            rubric_revision_ref=payload["rubric_revision_ref"],
            response_evidence_ref=payload["response_evidence_ref"],
            observations=tuple(
                CriterionObservation.from_mapping(item) for item in raw_observations
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        """Return the exact domain-neutral published-language envelope."""
        return {
            "contract_id": self.contract_id,
            "invocation_ref": self.invocation_ref,
            "configuration": self.configuration.to_payload(),
            "task_revision_ref": self.task_revision_ref,
            "rubric_revision_ref": self.rubric_revision_ref,
            "response_evidence_ref": self.response_evidence_ref,
            "observations": [item.to_payload() for item in self.observations],
        }
