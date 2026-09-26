"""Per-call cost evidence that decides whether a route is servable free *now*.

A zero catalog price says a model *can* be free; it does not say the next call
will be. Experiential Labs is the motivating case: its promotional free tiers
have per-organization daily/hourly allowances, and once an organization has
paid (or opted into "credits overflow") calls past the allowance are billed
at list price instead of refused. The catalog cannot tell the two states apart,
so a static provider exclusion was the only safe rule so far.

This module replaces that rule with evidence from real responses:

* Every provider response the :class:`~contextual_orchestrator.orchestrator.ModelClient`
  reads (preflight probe, discovery probe, served call) is classified from its
  provider-reported per-call cost (:func:`classify_reported_cost`).
* ``cost == 0`` (and not BYOK) is ``FREE`` evidence; ``cost > 0`` is ``PAID``;
  anything missing, malformed, negative, non-finite, or BYOK is ``UNKNOWN``.
* :data:`FREE_SERVING_LEDGER` keeps the last verdict per ``(provider, model)``
  for this process. A ``PAID`` verdict demotes the route out of every free
  selector immediately.
* :func:`free_serving_admitted` is the one predicate discovery-time selection
  (``model_discovery.general_free_serving_candidates``) and serving-time
  selection (``TaskOrchestrator._is_free_agent``) share, so the two cannot
  disagree and leave a dead route occupying a free slot.

Providers in :data:`COST_EVIDENCE_REQUIRED_PROVIDERS` are fail-closed: without
a ``FREE`` verdict they are paid, whatever the catalog says. Other providers
keep catalog-price admission and are only demoted by explicit ``PAID``
evidence (most of them report no per-call cost at all).

Where the cost is read (verified against public docs, retrieved 2026-09-26):
Experiential Labs stamps the settled USD cost on the response body as
``usage.cost`` for every Chat Completions / Responses / Messages reply (the
final usage chunk when streaming), reports BYOK calls as ``cost: 0`` with
``usage.is_byok: true``, and omits ``usage.cost`` on ``Idempotency-Key``
requests (https://platform.experientiallabs.ai/docs/cost-api,
https://platform.experientiallabs.ai/llms.txt). OpenRouter uses the same
``usage.cost`` shape (https://openrouter.ai/docs/use-cases/usage-accounting).
No public document names a per-call cost *response header*; the documented
Experiential response headers are ``x-request-id``, ``x-gateway-provider``,
``x-gateway-zdr``, ``x-gateway-route-depth`` and ``x-gateway-route-reason``.
:data:`REPORTED_COST_HEADER` therefore stays ``None`` until a provider
documents one; when set, header and body must agree or the call is
``UNKNOWN``.
"""

from __future__ import annotations

import enum
import math
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

COST_EVIDENCE_REQUIRED_PROVIDERS: frozenset[str] = frozenset({"experiential_labs"})
"""Providers whose free status is decided only by per-call cost evidence.

Their catalog price (promotional or otherwise) never admits them to a free
selector on its own; see the module docstring.
"""

REPORTED_COST_USAGE_FIELD = "cost"
"""Documented ``usage`` field carrying the charged per-call cost in USD."""

REPORTED_COST_BYOK_FIELD = "is_byok"
"""Documented ``usage`` flag: BYOK calls report ``cost: 0`` but are billed upstream."""

REPORTED_COST_HEADER: str | None = None
"""Optional per-call cost response header (UNVERIFIED; no provider documents one).

Leave ``None`` unless a provider publishes the header name and format. When
set, a present header that cannot be parsed, or that disagrees with a present
body ``usage.cost``, classifies the call as ``UNKNOWN`` (fail-closed).
"""


class CostVerdict(str, enum.Enum):
    """Classification of one provider response's reported cost."""

    FREE = "free"
    PAID = "paid"
    UNKNOWN = "unknown"


def _parse_cost(value: object) -> Decimal | None:
    """Return a finite non-negative cost, or ``None`` for anything else."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        parsed = Decimal(repr(value))
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped or len(stripped) > 64:
            return None
        try:
            parsed = Decimal(stripped)
        except InvalidOperation:
            return None
    else:
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def _header_cost(headers: object) -> tuple[bool, Decimal | None]:
    """Return ``(present, parsed)`` for :data:`REPORTED_COST_HEADER`."""
    if REPORTED_COST_HEADER is None or headers is None:
        return False, None
    getter = getattr(headers, "get", None)
    if getter is None:
        return False, None
    raw = getter(REPORTED_COST_HEADER)
    if raw is None:
        return False, None
    return True, _parse_cost(raw)


def classify_reported_cost(
    usage: Mapping[str, Any] | None, headers: object = None
) -> CostVerdict:
    """Classify one response's provider-reported cost; unknown is never free.

    Args:
        usage: The response's ``usage`` object (or the final stream usage frame).
        headers: Optional response headers (any mapping-like with ``get``).

    Returns:
        ``FREE`` only for an explicit, parseable zero cost with an explicit
        ``is_byok: false``;
        ``PAID`` for an explicit positive cost; ``UNKNOWN`` otherwise.
    """
    body: Mapping[str, Any] = usage if isinstance(usage, Mapping) else {}
    body_present = REPORTED_COST_USAGE_FIELD in body
    body_cost = _parse_cost(body.get(REPORTED_COST_USAGE_FIELD)) if body_present else None
    header_present, header_cost = _header_cost(headers)
    if body_present and body_cost is None:
        return CostVerdict.UNKNOWN
    if header_present and header_cost is None:
        return CostVerdict.UNKNOWN
    if body_present and header_present and body_cost != header_cost:
        return CostVerdict.UNKNOWN
    cost = body_cost if body_present else header_cost
    if cost is None:
        return CostVerdict.UNKNOWN
    if cost > 0:
        return CostVerdict.PAID
    if body.get(REPORTED_COST_BYOK_FIELD) is not False:
        # BYOK settles cost 0 while the upstream provider bills the account, and
        # an absent flag is not evidence either: only an explicit
        # ``is_byok: false`` proves the zero is a platform-side free charge.
        return CostVerdict.UNKNOWN
    return CostVerdict.FREE


@dataclass(frozen=True)
class CostObservation:
    """The last cost verdict recorded for one route."""

    verdict: CostVerdict
    observed_at: float


class FreeServingLedger:
    """Thread-safe, process-local last-verdict store keyed by route identity."""

    def __init__(self, *, clock: Any = time.time) -> None:
        self._lock = threading.Lock()
        self._observations: dict[tuple[str, str], CostObservation] = {}
        self._clock = clock

    def record(self, provider_name: str, model_id: str, verdict: CostVerdict) -> None:
        """Record one verdict; ``UNKNOWN`` is kept only for evidence-required providers.

        A provider that never reports per-call cost would otherwise overwrite
        a meaningful ``PAID`` demotion with noise. For evidence-required
        providers ``UNKNOWN`` replaces an earlier ``FREE`` (fail-closed).
        """
        if not provider_name or not model_id:
            return
        if (
            verdict is CostVerdict.UNKNOWN
            and provider_name not in COST_EVIDENCE_REQUIRED_PROVIDERS
        ):
            return
        with self._lock:
            self._observations[(provider_name, model_id)] = CostObservation(
                verdict, float(self._clock())
            )

    def observation(self, provider_name: str, model_id: str) -> CostObservation | None:
        """Return the last observation for a route, if any."""
        with self._lock:
            return self._observations.get((provider_name, model_id))

    def verdict(self, provider_name: str, model_id: str) -> CostVerdict | None:
        """Return the last verdict for a route, if any."""
        observation = self.observation(provider_name, model_id)
        return observation.verdict if observation is not None else None

    def snapshot(self) -> dict[str, str]:
        """Return a JSON-safe ``"provider/model" -> verdict`` view for evidence files."""
        with self._lock:
            return {
                f"{provider}/{model}": observation.verdict.value
                for (provider, model), observation in sorted(self._observations.items())
            }

    def reset(self) -> None:
        """Forget every observation (tests and process-level resets)."""
        with self._lock:
            self._observations.clear()


FREE_SERVING_LEDGER = FreeServingLedger()
"""Process-wide ledger shared by discovery, preflight, and serving."""


def record_reported_cost(
    provider_name: str | None,
    model_id: str | None,
    usage: Mapping[str, Any] | None,
    headers: object = None,
    *,
    ledger: FreeServingLedger | None = None,
) -> CostVerdict:
    """Classify one response and record the verdict for its route."""
    verdict = classify_reported_cost(usage, headers)
    (ledger or FREE_SERVING_LEDGER).record(provider_name or "", model_id or "", verdict)
    return verdict


def free_serving_admitted(
    provider_name: str | None,
    model_id: str | None,
    *,
    catalog_free: bool,
    ledger: FreeServingLedger | None = None,
) -> bool:
    """Return whether a route may serve a free selector right now.

    * Evidence-required providers: only a last verdict of ``FREE``.
    * Every other provider: catalog-free and not demoted by a ``PAID`` verdict.
    """
    verdict = (ledger or FREE_SERVING_LEDGER).verdict(provider_name or "", model_id or "")
    if (provider_name or "") in COST_EVIDENCE_REQUIRED_PROVIDERS:
        return verdict is CostVerdict.FREE
    return bool(catalog_free) and verdict is not CostVerdict.PAID
