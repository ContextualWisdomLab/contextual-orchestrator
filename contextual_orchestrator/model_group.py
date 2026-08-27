"""Measured speed/stability routing inside a model group.

A *model group* bundles several provider endpoints that serve the same
underlying model (for example ``shared_reasoning_model`` may span differently
named provider endpoints). Callers may
address the group as one logical model; this module decides which member
endpoint actually serves each request using only measured evidence:

- **Stability** is the Beta-Bernoulli posterior mean of the per-attempt
  success probability with a Laplace (uniform) prior -- the rule of
  succession (Laplace, 1774; Gelman et al., 2013, *Bayesian Data Analysis*,
  3rd ed., section 2.4). Every completed attempt contributes exactly one
  Bernoulli observation.
- **Speed** is an exponentially weighted moving average of the observed
  end-to-end request latency with smoothing gain 1/8 -- the SRTT estimator of
  Jacobson (1988), *Congestion Avoidance and Control*, SIGCOMM '88. The same
  EWMA form is applied to observed generation throughput: when a provider
  reports completion token counts, tokens-per-second samples are retained as
  diagnostic evidence. Routing consistently uses latency-derived
  responses-per-second.
- **Score** is ``P(success | data) / EWMA latency``: expected successful
  responses per second. It has consistent physical units, uses no hand-tuned weights, and
  degenerates gracefully -- members without any observation share one
  identical neutral score, so ordering falls back to the caller's static
  ranking until real evidence exists.
"""

from __future__ import annotations

import math
import re
import threading

from .conventions import require_object_name

#: Smoothing gain of the latency EWMA (Jacobson 1988 uses alpha = 1/8).
EWMA_LATENCY_GAIN = 0.125

#: Beta prior pseudo-counts: Laplace's uniform Beta(1, 1) prior.
BETA_PRIOR_SUCCESS_COUNT = 1.0
BETA_PRIOR_FAILURE_COUNT = 1.0

#: Floor under the latency divisor so a zero/near-zero EWMA cannot explode
#: the score before any real latency is observable (1 ms).
MIN_ROUTING_LATENCY_SECONDS = 1e-3

#: Neutral score assigned to members with no observations yet. All unobserved
#: members share it exactly, which makes intra-group ordering fall back to the
#: caller's static ranking instead of inventing a preference.
UNOBSERVED_MEMBER_SCORE = BETA_PRIOR_SUCCESS_COUNT / (
    BETA_PRIOR_SUCCESS_COUNT + BETA_PRIOR_FAILURE_COUNT
)

_GROUP_NAME_NORMALIZE_RE = re.compile(r"[-\s]+")


def canonical_group_name(raw_name: str) -> str:
    """Normalize a group alias to its canonical snake_case name.

    Accepts a hyphenated form clients naturally type and the stored snake_case
    form interchangeably, then enforces this
    repository's two-or-more-word snake_case object-name convention.
    """
    if not isinstance(raw_name, str):
        raise TypeError("group name must be a string")
    normalized = _GROUP_NAME_NORMALIZE_RE.sub("_", raw_name.strip().lower())
    if not normalized or set(normalized) == {"_"}:
        raise ValueError("group name must contain at least one word character")
    require_object_name(normalized, "model_group.name")
    return normalized


class ModelGroupRouter:
    """Thread-safe, in-memory measured-performance ledger for group members."""

    def __init__(
        self,
        *,
        ewma_gain: float = EWMA_LATENCY_GAIN,
        min_latency_seconds: float = MIN_ROUTING_LATENCY_SECONDS,
        prior_resolver: Callable[[str], tuple[float, float]] | None = None,
    ) -> None:
        if not 0 < ewma_gain <= 1:
            raise ValueError("ewma_gain must be within (0, 1]")
        if not math.isfinite(min_latency_seconds) or min_latency_seconds <= 0:
            raise ValueError("min_latency_seconds must be finite and positive")
        self._ewma_gain = float(ewma_gain)
        self._min_latency_seconds = float(min_latency_seconds)
        self._prior_resolver = prior_resolver
        self._lock = threading.Lock()
        # member_id -> {"alpha", "beta", "ewma", "ewma_tps"}; ewma/ewma_tps are
        # None until the first observation of each kind arrives.
        self._members: dict[str, dict[str, float | None]] = {}

    def register_member(self, member_id: str) -> None:
        """Ensure a member exists in the ledger (idempotent, keeps history)."""
        with self._lock:
            self._members.setdefault(member_id, self._blank_state(member_id))

    def _blank_state(self, member_id: str) -> dict[str, float | None]:
        """Fresh per-member ledger row: Laplace prior counts, no speed samples."""
        if self._prior_resolver is not None:
            alpha, beta = self._prior_resolver(member_id)
        else:
            alpha, beta = BETA_PRIOR_SUCCESS_COUNT, BETA_PRIOR_FAILURE_COUNT
        return {
            "alpha": alpha,
            "beta": beta,
            "prior_alpha": alpha,
            "prior_beta": beta,
            "ewma": None,
            "ewma_tps": None,
        }

    def forget_members(self, keep_member_ids: set[str]) -> None:
        """Drop ledger rows for members that left every group."""
        with self._lock:
            for member_id in list(self._members):
                if member_id not in keep_member_ids:
                    del self._members[member_id]

    def reset_members(self, member_ids: set[str]) -> None:
        """Discard measurements whose group context changed."""
        with self._lock:
            for member_id in member_ids:
                self._members.pop(member_id, None)

    def observe_success(
        self,
        member_id: str,
        latency_seconds: float,
        output_tokens: int | None = None,
    ) -> None:
        """Record one successful attempt with its measured wall-clock latency.

        ``output_tokens`` carries the provider-reported completion token count
        for the same attempt. When supplied it also feeds the tokens-per-second
        EWMA (Jacobson 1988 estimator applied to throughput samples); when
        omitted only latency evidence is recorded and no token count is ever
        inferred or invented.
        """
        if isinstance(latency_seconds, bool) or not isinstance(latency_seconds, (int, float)):
            raise TypeError("latency_seconds must be a real number")
        latency = float(latency_seconds)
        if not math.isfinite(latency):
            raise ValueError("latency_seconds must be finite")
        if latency < 0:
            raise ValueError("latency_seconds must be nonnegative")
        if output_tokens is not None and (
            isinstance(output_tokens, bool)
            or not isinstance(output_tokens, int)
            or output_tokens <= 0
        ):
            raise ValueError("output_tokens must be a positive integer when provided")
        clamped = max(latency, self._min_latency_seconds)
        try:
            throughput_sample = None if output_tokens is None else float(output_tokens) / clamped
        except OverflowError:
            raise ValueError("output_tokens must be representable as a finite float") from None
        if throughput_sample is not None and not math.isfinite(throughput_sample):
            raise ValueError("output_tokens must be representable as a finite float")
        with self._lock:
            state = self._ensure_locked(member_id)
            state["alpha"] = float(state["alpha"]) + 1.0
            ewma = state["ewma"]
            state["ewma"] = (
                clamped
                if ewma is None
                else (1.0 - self._ewma_gain) * float(ewma) + self._ewma_gain * clamped
            )
            if throughput_sample is not None:
                tps = state["ewma_tps"]
                state["ewma_tps"] = (
                    throughput_sample
                    if tps is None
                    else (1.0 - self._ewma_gain) * float(tps)
                    + self._ewma_gain * throughput_sample
                )

    def observe_failure(self, member_id: str) -> None:
        """Record one failed attempt (stability evidence only; no latency)."""
        with self._lock:
            state = self._ensure_locked(member_id)
            state["beta"] = float(state["beta"]) + 1.0

    def member_score(self, member_id: str) -> float:
        """Return the expected successful responses per second for a member."""
        with self._lock:
            return self._score_locked(member_id)

    def member_observation_count(self, member_id: str) -> int:
        """Total completed attempts recorded for one member (success + failure)."""
        with self._lock:
            state = self._members.get(member_id)
            if state is None:
                return 0
            alpha = float(state["alpha"]) - float(state.get("prior_alpha", BETA_PRIOR_SUCCESS_COUNT))
            beta = float(state["beta"]) - float(state.get("prior_beta", BETA_PRIOR_FAILURE_COUNT))
            return int(max(alpha, 0.0)) + int(max(beta, 0.0))

    def ranked_member_ids(self, member_ids: list[str] | tuple[str, ...]) -> list[str]:
        """Order member ids best-first by measured score, preserving input ties."""
        scored = {member_id: self.member_score(member_id) for member_id in member_ids}
        return sorted(member_ids, key=lambda member_id: -scored[member_id])

    def member_report(self, member_id: str) -> dict[str, float | int | None]:
        """One member's measured evidence row for admin/analytics surfaces."""
        with self._lock:
            return self._report_locked(member_id)

    def snapshot(self) -> dict[str, dict[str, float | int | None]]:
        """Copy of every member's report keyed by member id."""
        with self._lock:
            return {member_id: self._report_locked(member_id) for member_id in self._members}

    # --- internal helpers (callers must hold ``self._lock``) ---------------

    def _ensure_locked(self, member_id: str) -> dict[str, float | None]:
        return self._members.setdefault(member_id, self._blank_state(member_id))

    def _score_locked(self, member_id: str) -> float:
        state = self._members.get(member_id)
        if state is None:
            return UNOBSERVED_MEMBER_SCORE
        alpha = float(state["alpha"])
        beta = float(state["beta"])
        stability = alpha / (alpha + beta)
        ewma = state["ewma"]
        if ewma is None:
            # Unobserved members share one neutral reference latency so their
            # scores are identical and static ordering survives untouched.
            return stability / 1.0
        return stability / max(float(ewma), self._min_latency_seconds)

    def _report_locked(self, member_id: str) -> dict[str, float | int | None]:
        state = self._members.get(member_id)
        if state is None:
            return {
                "success_posterior_mean": UNOBSERVED_MEMBER_SCORE,
                "ewma_latency_seconds": None,
                "ewma_tokens_per_second": None,
                "success_count": 0,
                "failure_count": 0,
                "score": UNOBSERVED_MEMBER_SCORE,
            }
        alpha = float(state["alpha"])
        beta = float(state["beta"])
        ewma = state["ewma"]
        ewma_tps = state["ewma_tps"]
        return {
            "success_posterior_mean": round(alpha / (alpha + beta), 6),
            "ewma_latency_seconds": None if ewma is None else round(float(ewma), 6),
            "ewma_tokens_per_second": (
                None if ewma_tps is None else round(float(ewma_tps), 6)
            ),
            "success_count": int(alpha - float(state.get("prior_alpha", BETA_PRIOR_SUCCESS_COUNT))),
            "failure_count": int(beta - float(state.get("prior_beta", BETA_PRIOR_FAILURE_COUNT))),
            "score": round(self._score_locked(member_id), 9),
        }
