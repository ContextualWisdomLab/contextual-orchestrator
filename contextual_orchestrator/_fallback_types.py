"""Validated value objects for transport-neutral model fallback policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1
ALLOWED_VISIBILITIES = frozenset({"public", "private", "internal"})
CANDIDATE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
AGENT_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
PROVIDER_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}\Z")
CREDENTIAL_RE = re.compile(r"[A-Z][A-Z0-9_]{1,127}\Z")
CAPABILITY_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")


class CandidateValidationError(ValueError):
    """Report invalid trusted candidate or runtime-context control data."""


class FallbackManifestError(ValueError):
    """Report malformed or unsupported fallback-manifest input."""


class NoEligibleCandidateError(RuntimeError):
    """Report that every declared candidate was filtered from the plan."""


class CostTier(str, Enum):
    """Declare whether a model candidate incurs provider inference charges."""

    FREE = "free"
    PAID = "paid"


@dataclass(frozen=True, slots=True)
class FallbackCandidate:
    """Describe one trusted model target without storing secret values."""

    candidate_id: str
    provider: str
    model: str
    cost_tier: CostTier
    priority: int = 100
    required_credentials: tuple[str, ...] = ()
    repository_visibilities: frozenset[str] = ALLOWED_VISIBILITIES
    capabilities: frozenset[str] = frozenset({"text"})

    def __post_init__(self) -> None:
        """Validate fields before a candidate reaches a workflow adapter."""
        if not isinstance(self.candidate_id, str) or not CANDIDATE_ID_RE.fullmatch(
            self.candidate_id
        ):
            raise CandidateValidationError(
                "candidate_id must be a shell-safe identifier"
            )
        if not isinstance(self.provider, str) or not PROVIDER_RE.fullmatch(
            self.provider
        ):
            raise CandidateValidationError(
                "provider must be lowercase and shell-safe"
            )
        if not isinstance(self.model, str) or not MODEL_RE.fullmatch(self.model):
            raise CandidateValidationError(
                "model must be a non-empty shell-safe model identifier"
            )
        if not isinstance(self.cost_tier, CostTier):
            raise CandidateValidationError(
                "cost_tier must be CostTier.FREE or CostTier.PAID"
            )
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise CandidateValidationError("priority must be an integer")
        if self.priority < 0 or self.priority > 1_000_000:
            raise CandidateValidationError(
                "priority must be between 0 and 1000000"
            )
        if not isinstance(self.required_credentials, tuple):
            raise CandidateValidationError(
                "required_credentials must be a tuple"
            )
        validate_credentials(self.required_credentials)
        validate_visibilities(self.repository_visibilities)
        validate_capabilities(self.capabilities)

    def to_public_dict(self) -> dict[str, Any]:
        """Return JSON-safe metadata that never contains secret values."""
        return {
            "candidate_id": self.candidate_id,
            "provider": self.provider,
            "model": self.model,
            "cost_tier": self.cost_tier.value,
            "priority": self.priority,
            "required_credentials": list(self.required_credentials),
            "repository_visibilities": sorted(self.repository_visibilities),
            "capabilities": sorted(self.capabilities),
        }


@dataclass(frozen=True, slots=True)
class FallbackContext:
    """Describe request-time constraints used to filter candidates."""

    repository_visibility: str = "public"
    available_credentials: frozenset[str] = frozenset()
    required_capabilities: frozenset[str] = frozenset()
    allow_paid: bool = True

    def __post_init__(self) -> None:
        """Validate context vocabulary before policy evaluation."""
        if (
            not isinstance(self.repository_visibility, str)
            or self.repository_visibility not in ALLOWED_VISIBILITIES
        ):
            raise CandidateValidationError(
                "repository visibility must be public, private, or internal"
            )
        if not isinstance(self.available_credentials, frozenset):
            raise CandidateValidationError(
                "available_credentials must be a frozenset"
            )
        validate_credentials(tuple(self.available_credentials))
        validate_capabilities(self.required_capabilities)
        if not isinstance(self.allow_paid, bool):
            raise CandidateValidationError("allow_paid must be a boolean")


@dataclass(frozen=True, slots=True)
class SkippedCandidate:
    """Record why a candidate was excluded without recording secrets."""

    candidate_id: str
    reason: str

    def to_public_dict(self) -> dict[str, str]:
        """Return the JSON-safe skipped-candidate record."""
        return {"candidate_id": self.candidate_id, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class FallbackPlan:
    """Hold an eligible, deterministic free-first candidate sequence."""

    candidates: tuple[FallbackCandidate, ...]
    skipped: tuple[SkippedCandidate, ...] = ()

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        """Return candidate identifiers in execution order."""
        return tuple(candidate.candidate_id for candidate in self.candidates)

    @property
    def free_candidates(self) -> tuple[FallbackCandidate, ...]:
        """Return the free portion of the execution plan."""
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.cost_tier is CostTier.FREE
        )

    @property
    def paid_candidates(self) -> tuple[FallbackCandidate, ...]:
        """Return paid fallbacks after every eligible free candidate."""
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.cost_tier is CostTier.PAID
        )

    def to_public_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation of the policy decision."""
        return {
            "schema_version": SCHEMA_VERSION,
            "candidates": [
                candidate.to_public_dict() for candidate in self.candidates
            ],
            "skipped": [candidate.to_public_dict() for candidate in self.skipped],
        }


def validate_credentials(credentials: Sequence[str]) -> None:
    """Validate credential names without reading credential values."""
    if isinstance(credentials, (str, bytes)):
        raise CandidateValidationError(
            "credential names must be a sequence"
        )
    for credential in credentials:
        if not isinstance(credential, str) or not CREDENTIAL_RE.fullmatch(
            credential
        ):
            raise CandidateValidationError(
                "credential names must be uppercase environment identifiers"
            )


def validate_visibilities(visibilities: frozenset[str]) -> None:
    """Validate non-empty repository-visibility eligibility."""
    if not isinstance(visibilities, frozenset) or not visibilities:
        raise CandidateValidationError(
            "repository visibility set must be non-empty"
        )
    unknown = set(visibilities) - ALLOWED_VISIBILITIES
    if unknown:
        raise CandidateValidationError(
            f"unknown repository visibility: {joined(unknown)}"
        )


def validate_capabilities(capabilities: frozenset[str]) -> None:
    """Validate capability labels used by the eligibility filter."""
    if not isinstance(capabilities, frozenset):
        raise CandidateValidationError("capabilities must be a frozenset")
    for capability in capabilities:
        if not isinstance(capability, str) or not CAPABILITY_RE.fullmatch(
            capability
        ):
            raise CandidateValidationError(
                "capability names must be lowercase shell-safe identifiers"
            )


def joined(values: Iterable[object]) -> str:
    """Return stable comma-separated diagnostics for unordered values."""
    return ",".join(sorted(str(value) for value in values))
