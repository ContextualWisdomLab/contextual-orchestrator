"""Eligibility filtering and deterministic ordering for model fallbacks."""

from __future__ import annotations

from typing import Iterable

from ._fallback_types import (
    CandidateValidationError,
    CostTier,
    FallbackCandidate,
    FallbackContext,
    FallbackPlan,
    NoEligibleCandidateError,
    SkippedCandidate,
)


def build_fallback_plan(
    candidates: Iterable[FallbackCandidate],
    *,
    context: FallbackContext | None = None,
) -> FallbackPlan:
    """Filter candidates and place every free fallback before paid ones.

    Ordering is deterministic: cost tier, numeric priority, and then trusted
    declaration order. Duplicate identities are rejected before filtering so
    aliases cannot accidentally repeat a billed provider request.
    """
    candidate_tuple = tuple(candidates)
    _validate_candidate_collection(candidate_tuple)
    runtime_context = context or FallbackContext()
    eligible: list[tuple[int, FallbackCandidate]] = []
    skipped: list[SkippedCandidate] = []

    for index, candidate in enumerate(candidate_tuple):
        reason = _ineligibility_reason(candidate, runtime_context)
        if reason is None:
            eligible.append((index, candidate))
        else:
            skipped.append(SkippedCandidate(candidate.candidate_id, reason))

    if not eligible:
        reasons = ", ".join(
            f"{item.candidate_id}={item.reason}" for item in skipped
        ) or "candidate list was empty"
        raise NoEligibleCandidateError(f"no eligible candidates: {reasons}")

    eligible.sort(
        key=lambda item: (
            0 if item[1].cost_tier is CostTier.FREE else 1,
            item[1].priority,
            item[0],
        )
    )
    return FallbackPlan(
        candidates=tuple(candidate for _, candidate in eligible),
        skipped=tuple(skipped),
    )


def validate_candidate_collection(
    candidates: tuple[FallbackCandidate, ...]
) -> None:
    """Validate a collection for manifest callers."""
    _validate_candidate_collection(candidates)


def _validate_candidate_collection(
    candidates: tuple[FallbackCandidate, ...]
) -> None:
    """Reject empty or duplicate candidate identities."""
    if not candidates:
        raise NoEligibleCandidateError(
            "no eligible candidates: candidate list was empty"
        )
    candidate_ids: set[str] = set()
    provider_models: set[tuple[str, str]] = set()
    for candidate in candidates:
        if not isinstance(candidate, FallbackCandidate):
            raise CandidateValidationError(
                "every candidate must be FallbackCandidate"
            )
        if candidate.candidate_id in candidate_ids:
            raise CandidateValidationError(
                f"duplicate candidate_id: {candidate.candidate_id}"
            )
        provider_model = (candidate.provider, candidate.model)
        if provider_model in provider_models:
            raise CandidateValidationError(
                f"duplicate provider/model: "
                f"{candidate.provider}/{candidate.model}"
            )
        candidate_ids.add(candidate.candidate_id)
        provider_models.add(provider_model)


def _ineligibility_reason(
    candidate: FallbackCandidate, context: FallbackContext
) -> str | None:
    """Return a public exclusion reason or ``None`` when eligible."""
    if context.repository_visibility not in candidate.repository_visibilities:
        return "repository_visibility"
    missing_credentials = sorted(
        set(candidate.required_credentials)
        - set(context.available_credentials)
    )
    if missing_credentials:
        return f"missing_credentials:{','.join(missing_credentials)}"
    missing_capabilities = sorted(
        set(context.required_capabilities) - set(candidate.capabilities)
    )
    if missing_capabilities:
        return f"missing_capabilities:{','.join(missing_capabilities)}"
    if candidate.cost_tier is CostTier.PAID and not context.allow_paid:
        return "paid_candidates_disabled"
    return None
