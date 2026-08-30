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
import time
from collections.abc import Callable

from .conventions import require_object_name
from .routing_observation_store import RoutingObservationStore

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


class RoutingObservationPersistenceError(RuntimeError):
    """A configured durable routing observation could not be recorded."""


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
    """Thread-safe measured-performance ledger for model-group members.

    The default ledger is process-local.  Supplying a
    :class:`RoutingObservationStore` makes the same measured observations
    visible to other gateway processes inside an explicit time window.
    """

    def __init__(
        self,
        *,
        ewma_gain: float = EWMA_LATENCY_GAIN,
        min_latency_seconds: float = MIN_ROUTING_LATENCY_SECONDS,
        prior_resolver: Callable[[str], tuple[float, float]] | None = None,
        observation_context_resolver: Callable[[str], str] | None = None,
        observation_store: RoutingObservationStore | None = None,
        ledger_name: str = "transport",
    ) -> None:
        if not 0 < ewma_gain <= 1:
            raise ValueError("ewma_gain must be within (0, 1]")
        if not math.isfinite(min_latency_seconds) or min_latency_seconds <= 0:
            raise ValueError("min_latency_seconds must be finite and positive")
        self._ewma_gain = float(ewma_gain)
        self._min_latency_seconds = float(min_latency_seconds)
        self._prior_resolver = prior_resolver
        self._observation_context_resolver = observation_context_resolver
        if observation_store is not None and any(
            not callable(getattr(observation_store, name, None))
            for name in ("append", "load", "delete_members")
        ):
            raise TypeError("observation_store must implement the routing observation contract")
        if type(ledger_name) is not str or not ledger_name.strip():
            raise ValueError("ledger_name must be a non-empty string")
        self._observation_store = observation_store
        self._ledger_name = ledger_name.strip()
        self._lock = threading.Lock()
        # Store I/O stays serialized with in-memory updates under the same lock
        # ordering so refresh=False reads never observe a partially refreshed row set.
        self._observation_io_lock = threading.Lock()
        self._member_contexts: dict[str, str] = {}
        # member_id -> {"alpha", "beta", "ewma", "ewma_tps"}; ewma/ewma_tps are
        # None until the first observation of each kind arrives.
        self._members: dict[str, dict[str, float | None]] = {}

    def register_member(self, member_id: str) -> None:
        """Ensure a member exists in the ledger (idempotent, keeps history)."""
        with self._lock:
            self._member_contexts[member_id] = self._resolve_context_key(member_id)
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

    @staticmethod
    def _float_value(value: float | None, default: float = 0.0) -> float:
        """Read an optional numeric state value without changing valid zeroes."""
        return default if value is None else float(value)

    def forget_members(self, keep_member_ids: set[str]) -> None:
        """Drop ledger rows for members that left every group."""
        if self._observation_store is None:
            with self._lock:
                for member_id in list(self._members):
                    if member_id not in keep_member_ids:
                        del self._members[member_id]
                        self._member_contexts.pop(member_id, None)
            return
        with self._lock:
            with self._observation_io_lock:
                removed = set(self._members) - keep_member_ids
                self._observation_store.delete_members(self._ledger_name, removed)
                for member_id in removed:
                    if member_id not in keep_member_ids:
                        self._members.pop(member_id, None)
                        self._member_contexts.pop(member_id, None)

    def reset_members(self, member_ids: set[str]) -> None:
        """Discard measurements whose group context changed."""
        if self._observation_store is None:
            with self._lock:
                for member_id in member_ids:
                    self._members.pop(member_id, None)
                    self._member_contexts.pop(member_id, None)
            return
        with self._lock:
            with self._observation_io_lock:
                self._observation_store.delete_members(self._ledger_name, member_ids)
                for member_id in member_ids:
                    self._members.pop(member_id, None)
                    self._member_contexts.pop(member_id, None)

    def update_prior(
        self,
        member_id: str,
        prior_alpha: float,
        prior_beta: float,
    ) -> None:
        """Replace a member's prior evidence without touching outcomes.

        Callers (benchmark initialization, telemetry collectors) own the
        prior component; this ledger owns measured outcomes. The current
        ``alpha``/``beta`` mass shifts by exactly the same delta as the
        prior pair, so ``success_count``/``failure_count`` — the ledger's
        observed-outcome accounting — remain bit-identical.

        Args:
            member_id: Ledger member to refresh.
            prior_alpha: New prior pseudo-successes (finite, non-negative).
            prior_beta: New prior pseudo-failures (finite, non-negative).

        Raises:
            ValueError: If the supplied components are not finite or negative.
        """
        for name, value in (("prior_alpha", prior_alpha), ("prior_beta", prior_beta)):
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        with self._lock:
            state = self._ensure_locked(member_id)
            old_alpha = self._float_value(state.get("prior_alpha"))
            old_beta = self._float_value(state.get("prior_beta"))
            delta_alpha = float(prior_alpha) - old_alpha
            delta_beta = float(prior_beta) - old_beta
            state["prior_alpha"] = float(prior_alpha)
            state["prior_beta"] = float(prior_beta)
            state["alpha"] = float(state.get("alpha") or 0.0) + delta_alpha
            state["beta"] = float(state.get("beta") or 0.0) + delta_beta

    def observe_success(
        self,
        member_id: str,
        latency_seconds: float,
        output_tokens: int | None = None,
        *,
        observation_context_key: str | None = None,
        observed_at: float | None = None,
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
        when = self._resolve_observed_at(observed_at)
        with self._lock:
            with self._observation_io_lock:
                self._persist_observation(
                    member_id,
                    observation_context_key=observation_context_key,
                    observed_at=when,
                    success=True,
                    latency_seconds=latency,
                    output_tokens=output_tokens,
                )
                state = self._ensure_locked(
                    member_id,
                    observation_context_key=observation_context_key,
                )
                self._apply_success_locked(state, clamped, throughput_sample)

    def observe_failure(
        self,
        member_id: str,
        *,
        observation_context_key: str | None = None,
        observed_at: float | None = None,
    ) -> None:
        """Record one failed attempt (stability evidence only; no latency)."""
        when = self._resolve_observed_at(observed_at)
        with self._lock:
            with self._observation_io_lock:
                self._persist_observation(
                    member_id,
                    observation_context_key=observation_context_key,
                    observed_at=when,
                    success=False,
                )
                state = self._ensure_locked(
                    member_id,
                    observation_context_key=observation_context_key,
                )
                self._apply_failure_locked(state)

    def _resolve_observed_at(self, observed_at: float | None) -> float:
        """Resolve one observation timestamp before any router lock can delay it."""
        if observed_at is None:
            store_now = getattr(self._observation_store, "_now", None)
            return float(store_now()) if callable(store_now) else time.time()
        return float(observed_at)

    def _persist_observation(
        self,
        member_id: str,
        *,
        observation_context_key: str | None = None,
        observed_at: float | None = None,
        success: bool,
        latency_seconds: float | None = None,
        output_tokens: int | None = None,
    ) -> None:
        """Persist one observation while keeping storage failures identifiable."""
        if self._observation_store is None:
            return
        when = self._resolve_observed_at(observed_at)
        try:
            self._observation_store.append(
                self._ledger_name,
                member_id,
                context_key=(
                    observation_context_key
                    if observation_context_key is not None
                    else self._context_key_locked(
                        member_id,
                        observation_context_key=observation_context_key,
                    )
                ),
                observed_at=when,
                success=success,
                latency_seconds=latency_seconds,
                output_tokens=output_tokens,
            )
        except Exception as exc:  # noqa: BLE001 - preserve the durable boundary type
            raise RoutingObservationPersistenceError(
                "durable routing observation could not be recorded"
            ) from exc

    def refresh(self) -> None:
        """Reload current-window observations from the shared store."""
        if self._observation_store is None:
            return
        with self._lock:
            with self._observation_io_lock:
                observations = self._observation_store.load(
                    self._ledger_name,
                    active_contexts=dict(self._member_contexts),
                )
                # ponytail: replay the bounded window for cross-process
                # correctness; add a sequence cursor only after measured fleet
                # load requires it.
                member_ids = tuple(self._members)
                prior_by_member = {
                    member_id: (
                        self._float_value(
                            state.get("prior_alpha"), BETA_PRIOR_SUCCESS_COUNT
                        ),
                        self._float_value(
                            state.get("prior_beta"), BETA_PRIOR_FAILURE_COUNT
                        ),
                    )
                    for member_id, state in self._members.items()
                }
                rebuilt = {
                    member_id: self._blank_state(member_id) for member_id in member_ids
                }
                for member_id, (prior_alpha, prior_beta) in prior_by_member.items():
                    state = rebuilt[member_id]
                    state["alpha"] = prior_alpha
                    state["beta"] = prior_beta
                    state["prior_alpha"] = prior_alpha
                    state["prior_beta"] = prior_beta
                for observation in observations:
                    if observation.member_id not in rebuilt:
                        continue
                    state = rebuilt[observation.member_id]
                    if observation.success:
                        if observation.latency_seconds is None:
                            continue
                        latency = max(float(observation.latency_seconds), self._min_latency_seconds)
                        throughput = (
                            None
                            if observation.output_tokens is None
                            else float(observation.output_tokens) / latency
                        )
                        self._apply_success_locked(state, latency, throughput)
                    else:
                        self._apply_failure_locked(state)
                self._members = rebuilt

    def member_score(self, member_id: str) -> float:
        """Return the expected successful responses per second for a member."""
        self.refresh()
        with self._lock:
            return self._score_locked(member_id)

    def member_observation_count(self, member_id: str, *, refresh: bool = True) -> int:
        """Total completed attempts recorded for one member (success + failure)."""
        if refresh:
            self.refresh()
        with self._lock:
            state = self._members.get(member_id)
            if state is None:
                return 0
            alpha = self._float_value(state["alpha"]) - self._float_value(
                state.get("prior_alpha"), BETA_PRIOR_SUCCESS_COUNT
            )
            beta = self._float_value(state["beta"]) - self._float_value(
                state.get("prior_beta"), BETA_PRIOR_FAILURE_COUNT
            )
            return int(max(alpha, 0.0)) + int(max(beta, 0.0))

    def ranked_member_ids(
        self,
        member_ids: list[str] | tuple[str, ...],
        *,
        refresh: bool = True,
    ) -> list[str]:
        """Order member ids best-first by measured score, preserving input ties."""
        if refresh:
            self.refresh()
        with self._lock:
            scored = {member_id: self._score_locked(member_id) for member_id in member_ids}
            return sorted(member_ids, key=lambda member_id: -scored[member_id])

    def member_report(
        self, member_id: str, *, refresh: bool = True
    ) -> dict[str, float | int | None]:
        """One member's measured evidence row for admin/analytics surfaces."""
        if refresh:
            self.refresh()
        with self._lock:
            return self._report_locked(member_id)

    def snapshot(
        self, *, refresh: bool = True
    ) -> dict[str, dict[str, float | int | None]]:
        """Copy of every member's report keyed by member id."""
        if refresh:
            self.refresh()
        with self._lock:
            return {member_id: self._report_locked(member_id) for member_id in self._members}

    # --- internal helpers (callers must hold ``self._lock``) ---------------

    def _ensure_locked(
        self,
        member_id: str,
        *,
        observation_context_key: str | None = None,
    ) -> dict[str, float | None]:
        if member_id not in self._member_contexts:
            self._member_contexts[member_id] = (
                observation_context_key
                if observation_context_key is not None
                else self._resolve_context_key(member_id)
            )
        return self._members.setdefault(member_id, self._blank_state(member_id))

    def _resolve_context_key(self, member_id: str) -> str:
        context_key = (
            self._observation_context_resolver(member_id)
            if self._observation_context_resolver is not None
            else member_id
        )
        if type(context_key) is not str or not context_key:
            raise ValueError("observation_context_resolver must return a non-empty string")
        return context_key

    def _context_key_locked(
        self,
        member_id: str,
        *,
        observation_context_key: str | None = None,
    ) -> str:
        if member_id not in self._member_contexts:
            self._member_contexts[member_id] = (
                observation_context_key
                if observation_context_key is not None
                else self._resolve_context_key(member_id)
            )
        return self._member_contexts[member_id]

    def _apply_success_locked(
        self,
        state: dict[str, float | None],
        latency: float,
        throughput_sample: float | None,
    ) -> None:
        """Apply one already-validated success while the router lock is held."""
        state["alpha"] = self._float_value(state["alpha"]) + 1.0
        ewma = state["ewma"]
        state["ewma"] = (
            latency
            if ewma is None
            else (1.0 - self._ewma_gain) * self._float_value(ewma)
            + self._ewma_gain * latency
        )
        if throughput_sample is not None:
            tps = state["ewma_tps"]
            state["ewma_tps"] = (
                throughput_sample
                if tps is None
                else (1.0 - self._ewma_gain) * self._float_value(tps)
                + self._ewma_gain * throughput_sample
            )

    @staticmethod
    def _apply_failure_locked(state: dict[str, float | None]) -> None:
        """Apply one already-validated failure while the router lock is held."""
        state["beta"] = ModelGroupRouter._float_value(state["beta"]) + 1.0

    def _score_locked(self, member_id: str) -> float:
        state = self._members.get(member_id)
        if state is None:
            return UNOBSERVED_MEMBER_SCORE
        alpha = self._float_value(state["alpha"])
        beta = self._float_value(state["beta"])
        stability = alpha / (alpha + beta)
        ewma = state["ewma"]
        if ewma is None:
            # Unobserved members share one neutral reference latency so their
            # scores are identical and static ordering survives untouched.
            return stability / 1.0
        return stability / max(self._float_value(ewma), self._min_latency_seconds)

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
        alpha = self._float_value(state["alpha"])
        beta = self._float_value(state["beta"])
        ewma = state["ewma"]
        ewma_tps = state["ewma_tps"]
        return {
            "success_posterior_mean": round(alpha / (alpha + beta), 6),
            "ewma_latency_seconds": None if ewma is None else round(self._float_value(ewma), 6),
            "ewma_tokens_per_second": (
                None if ewma_tps is None else round(self._float_value(ewma_tps), 6)
            ),
            "success_count": int(
                alpha
                - self._float_value(state.get("prior_alpha"), BETA_PRIOR_SUCCESS_COUNT)
            ),
            "failure_count": int(
                beta
                - self._float_value(state.get("prior_beta"), BETA_PRIOR_FAILURE_COUNT)
            ),
            "score": round(self._score_locked(member_id), 9),
        }
