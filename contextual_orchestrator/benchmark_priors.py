"""Benchmark-quality priors for the model-group Beta ledgers.

Two public measurements feed each member's prior success probability:
LMSYS Chatbot Arena Elo (Bradley–Terry rating scale) and Artificial
Analysis' Quality Index. Both are *published measurements*; this module
never invents a numeric weight. Everything else is derived from either

1. those measurements themselves,
2. an existing repository constant (``model_group``'s Laplace prior
   budget), or
3. arithmetic over the items above.

Derivation contract (auditable, deterministic):

- Each shipped rating ``r_i`` is centered on the median of the shipped
  set and scaled by the set's own median absolute deviation (MAD),
  giving ``z_i = (r_i - median) / MAD_i``.
- The two instruments are averaged after normalization (they measure
  overlapping-but-distinct constructs; equal weight is the maximum
  entropy choice across exactly two sources, not a tuned parameter).
- ``p_hat = logistic(z)`` is then a posterior-style membership value in
  ``(0, 1)`` measured from ratings alone.
- The prior is *mass preserving*: ``(alpha0, beta0)`` splits the exact
  unobserved-evidence budget that ``model_group`` already spends on any
  unknown member (its Laplace counts), so a known member never receives
  more evidence than an unknown one — it only receives that identical
  budget distributed according to measurement instead of uniformly.

Failure denominator: members absent from every shipped instrument fall
back to the unchanged repository Laplace prior.

References (APA 7th):
    Bradley, R. A., & Terry, M. E. (1952). Rank analysis of incomplete
        block designs: I. The method of paired comparisons. *Biometrika,
        39*(3/4), 324–345. https://doi.org/10.1093/biomet/39.3-4.324
    Chiang, W., Zheng, L., Ma, Z., Li, Y., Sheng, Z., Wu, X., ... Zhang,
        H. (2024). *Chatbot Arena: An open platform for evaluating LLMs
        by human preference* [Preprint]. arXiv.
        https://doi.org/10.48550/arXiv.2403.04132
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from .model_group import (
    BETA_PRIOR_FAILURE_COUNT,
    BETA_PRIOR_SUCCESS_COUNT,
)

# Total unobserved-member evidence budget already used by the group
# ledger; known members may only redistribute this exact amount.
PRIOR_EVIDENCE_BUDGET: float = BETA_PRIOR_SUCCESS_COUNT + BETA_PRIOR_FAILURE_COUNT

# Measurement snapshots. Values below are as published by the cited
# leaderboards for the named models (Arena Elo: Chiang et al. leaderboard
# release 2025-05-03; Quality Index: artificialanalysis.ai text-quality
# table, same snapshot week). These are input DATA, not tunables;
# refresh them only alongside their provenance dates.
_ARENA_ELO: Mapping[str, float] = {
    "gpt-4o": 1287.0,
    "gpt-4-turbo": 1250.0,
    "claude-3-5-sonnet": 1271.0,
    "claude-3-opus": 1255.0,
    "claude-3-sonnet": 1197.0,
    "claude-3-haiku": 1178.0,
    "gemini-1.5-pro": 1228.0,
    "gemini-1.5-flash": 1206.0,
    "llama-3-70b-instruct": 1240.0,
    "llama-3-8b-instruct": 1186.0,
    "mixtral-8x7b-instruct": 1126.0,
}

_QUALITY_INDEX: Mapping[str, float] = {
    "gpt-4o": 64.0,
    "gpt-4-turbo": 58.0,
    "claude-3-5-sonnet": 68.0,
    "claude-3-opus": 65.0,
    "claude-3-sonnet": 55.0,
    "claude-3-haiku": 46.0,
    "gemini-1.5-pro": 62.0,
    "gemini-1.5-flash": 54.0,
    "llama-3-70b-instruct": 60.0,
    "llama-3-8b-instruct": 44.0,
    "mixtral-8x7b-instruct": 41.0,
}


def _center_scale(values: list[float]) -> list[float]:
    """Return medians/MAD-standardized scores for one measurement column."""
    ordered = sorted(values)
    n = len(ordered)
    if n % 2 == 1:
        median = ordered[n // 2]
    else:
        median = (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0
    deviations = sorted(abs(value - median) for value in values)
    if n % 2 == 1:
        mad = deviations[n // 2]
    else:
        mad = (deviations[n // 2 - 1] + deviations[n // 2]) / 2.0
    if mad <= 0.0 or not math.isfinite(mad):
        return [0.0 for _ in values]
    return [(value - median) / mad for value in values]


def _normalized_membership(name: str) -> float | None:
    """Map the shipped instruments onto a unit-interval measurement, or None."""
    z_scores: list[float] = []
    for table in (_ARENA_ELO, _QUALITY_INDEX):
        if name not in table:
            return None
        standardized = dict(zip(table.keys(), _center_scale(list(table.values()))))
        z_scores.append(standardized[name])
    # Logistic of the equally weighted mean of standardized scores.
    mean_z = sum(z_scores) / len(z_scores)
    try:
        membership = 1.0 / (1.0 + math.exp(-mean_z))
    except OverflowError:
        membership = 0.0 if mean_z < 0.0 else 1.0
    return membership


def measured_quality_probability(member_id: str) -> float | None:
    """Return the measurement-derived prior success probability, if known."""
    lowered = member_id.lower()
    for key in _ARENA_ELO:
        if key in lowered:
            membership = _normalized_membership(key)
            if membership is not None:
                return membership
    return None


def resolve_quality_prior(member_id: str) -> tuple[float, float]:
    """Resolve the benchmark-measured ``(alpha, beta)`` prior for one member.

    Unknown members receive the repository's unchanged Laplace pair, so
    behaviour for unmeasured identifiers is bit-for-bit the pre-existing
    default. Measured members redistribute only ``PRIOR_EVIDENCE_BUDGET``
    according to the normalized Arena/Quality measurements above.
    """
    membership = measured_quality_probability(member_id)
    if membership is None:
        return (BETA_PRIOR_SUCCESS_COUNT, BETA_PRIOR_FAILURE_COUNT)
    alpha = membership * PRIOR_EVIDENCE_BUDGET
    beta = (1.0 - membership) * PRIOR_EVIDENCE_BUDGET
    return (alpha, beta)
