"""Per-call cost evidence that decides whether a route is servable free *now*.

A zero catalog price says a model *can* be free; it does not say the next call
will be. Experiential Labs is the motivating case: its promotional free tiers
have per-organization daily/hourly allowances, and once an organization has
paid (or opted into "credits overflow") calls past the allowance are billed
at list price instead of refused. The catalog cannot tell the two states apart,
so a static provider exclusion was the only safe rule so far.

This module replaces that rule with evidence from real responses:

* **Nomination.** A route becomes a free *candidate* from catalog evidence:
  a zero token price, or (Experiential Labs) a ``free: true`` entry in the
  public keyless ``GET /api/models`` ``promotions[]`` catalog
  (:func:`free_promotion_slugs`). A failed catalog fetch nominates nothing.
* **Evidence.** Every provider response the
  :class:`~contextual_orchestrator.orchestrator.ModelClient` reads (probe,
  preflight, served call) is classified from its provider-reported per-call
  cost (:func:`classify_reported_cost`): a JSON-number ``cost == 0`` with an
  explicit ``is_byok: false`` is ``FREE``; ``cost > 0`` is ``PAID``; anything
  missing, malformed (including numeric *strings*), negative, non-finite, or
  BYOK is ``UNKNOWN``. A 429 ``insufficient_quota`` / ``free_limit_reached``
  error is ``EXHAUSTED`` (:func:`is_free_quota_exhausted_error`); for
  evidence-required providers an HTTP 402 is ``EXHAUSTED`` too, and every
  other call that does not complete with a parsed cost (transport error,
  non-2xx, unreadable body, aborted stream) is ``UNKNOWN``
  (:func:`record_provider_error`, :func:`record_failed_call`). Requests sent
  with an ``Idempotency-Key`` carry no cost and are skipped entirely: they
  neither promote nor demote (:func:`request_has_idempotency_key`).
* **Ledger.** :data:`FREE_SERVING_LEDGER` keeps the last verdict per
  ``(provider, model)`` for this process, plus the time of the last demotion
  as a separate field. ``PAID`` and ``EXHAUSTED`` demote the route out of
  every free selector immediately, and the demotion holds until the next
  allowance reset after it, whatever is recorded in between (a later
  ``UNKNOWN`` cannot clear it and a ``FREE`` is rejected). A ``FREE`` verdict
  also expires at the next reset, so an idle route never stays free across
  resets without fresh evidence.
* **Reset.** The allowance resets at 00:00 UTC (09:00 KST). The ledger places
  the boundary :data:`ALLOWANCE_RESET_SKEW_SECONDS` (5 minutes) later, at
  00:05 UTC, so a few minutes of clock skew between this host and the
  provider cannot lift a demotion (or admit a probe) before the provider
  actually reset (:func:`last_allowance_reset`).
* **Admission.** :func:`free_serving_admitted` is the one predicate
  discovery-time selection (``model_discovery.general_free_serving_candidates``)
  and serving-time selection (``TaskOrchestrator._is_free_agent``) share, so
  the two cannot disagree and leave a dead route occupying a free slot.
  Providers in :data:`COST_EVIDENCE_REQUIRED_PROVIDERS` are fail-closed:
  without a ``FREE`` verdict they are paid, whatever the catalog says. Other
  providers keep catalog-price admission and are only demoted by explicit
  ``PAID``/``EXHAUSTED`` evidence.
* **Re-admission.** A route whose last observation predates the latest
  reset (demoted, unknown, or a stale ``FREE``) becomes *probe-due*
  (:meth:`FreeServingLedger.probe_due`). It is re-admitted only by fresh
  ``FREE`` evidence from that probe, never assumed free
  (:func:`probe_free_candidates`). A probe can be billed once when the free
  allowance is already used up and the organization has credits overflow on;
  that single billed call demotes the route until the next reset and is an
  accepted trade-off.

Where the cost is read (documented; retrieved 2026-09-26): Experiential Labs
stamps the settled USD cost on the response body as ``usage.cost`` for every
Chat Completions / Responses / Messages reply (the final usage chunk when
streaming), reports BYOK calls as ``cost: 0`` with ``usage.is_byok: true``,
and omits ``usage.cost`` on ``Idempotency-Key`` requests
(https://platform.experientiallabs.ai/docs/cost-api,
https://platform.experientiallabs.ai/llms.txt). OpenRouter uses the same
``usage.cost`` shape (https://openrouter.ai/docs/use-cases/usage-accounting).
That a promotional free-tier call reports exactly ``cost: 0`` with
``is_byok: false`` is inferred from those docs and has not been observed on a
live response. No public document names a per-call cost *response header*;
:data:`REPORTED_COST_HEADER` stays ``None`` as an optional slot, and when set,
header and body must agree or the call is ``UNKNOWN``.

Known limitations (documented follow-ups): an hourly-allowance 429 holds the
route until the next *daily* reset (conservative); nothing inside the
orchestrator calls :func:`probe_free_candidates` yet (the review launcher
does); admission and dispatch are not atomic, so a call admitted just before
a concurrent demotion is still sent.
"""

from __future__ import annotations

import calendar
import enum
import math
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
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

IDEMPOTENCY_KEY_HEADER = "idempotency-key"
"""Request header whose responses omit ``usage.cost`` (documented); skipped."""

EXPERIENTIAL_PROMOTIONS_URL = "https://api.experientiallabs.ai/api/models?limit=1"
"""Public keyless catalog whose ``promotions[]`` nominates free candidates.

``limit=1`` keeps the model page small; ``promotions[]`` is returned whole.
"""

FREE_QUOTA_ERROR_MARKERS: frozenset[str] = frozenset(
    {"free_limit_reached", "insufficient_quota"}
)
"""Documented 429 error markers for an exhausted free allowance."""

PAYMENT_REQUIRED_STATUS = 402
"""HTTP status that demotes an evidence-required route (credits/allowance gone)."""

ALLOWANCE_RESET_SKEW_SECONDS = 300
"""Clock-skew margin added to the 00:00 UTC allowance reset (5 minutes).

The ledger treats 00:05 UTC as the reset so a host clock running a few minutes
ahead of the provider cannot lift a demotion, expire the hold, or schedule a
probe before the provider has actually reset. The cost is that a demotion
observed between 00:00 and 00:05 UTC (host clock) is attributed to the previous
allowance day and lifts at 00:05; the route then still needs a fresh ``FREE``
probe before it is admitted.
"""

_HEADER_COST_PATTERN = re.compile(r"[0-9]{1,20}(?:\.[0-9]{1,20})?", re.ASCII)


class CostVerdict(str, enum.Enum):
    """Classification of one provider response's reported cost."""

    FREE = "free"
    PAID = "paid"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


_DEMOTING_VERDICTS = frozenset({CostVerdict.PAID, CostVerdict.EXHAUSTED})


def _parse_cost(value: object) -> Decimal | None:
    """Return a finite non-negative cost from a real JSON number, else ``None``.

    Only ``int``/``float`` (never ``bool``) count: the documented ``usage.cost``
    is a JSON number, so a string such as ``"0"`` or ``"0E+5"`` is malformed
    evidence, not a zero charge.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        parsed = Decimal(repr(value))
    else:
        parsed = Decimal(value)
    if parsed < 0:
        return None
    return parsed


def _parse_header_cost(value: object) -> Decimal | None:
    """Parse an optional cost header: plain ASCII decimal digits only."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not _HEADER_COST_PATTERN.fullmatch(stripped):
        return None
    return Decimal(stripped)


def _header_value(headers: object, name: str) -> object:
    """Return one header value, case-insensitively, from a mapping or pairs."""
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if callable(getter):
        try:
            value = getter(name)
        except Exception:  # noqa: BLE001 - untrusted mapping-likes
            value = None
        if value is not None:
            return value
    items = getattr(headers, "items", None)
    try:
        pairs = items() if callable(items) else headers
        for pair in pairs:  # type: ignore[union-attr]
            if (
                isinstance(pair, tuple)
                and len(pair) == 2
                and str(pair[0]).casefold() == name.casefold()
            ):
                return pair[1]
    except TypeError:
        return None
    return None


def _header_cost(headers: object) -> tuple[bool, Decimal | None]:
    """Return ``(present, parsed)`` for :data:`REPORTED_COST_HEADER`."""
    if REPORTED_COST_HEADER is None:
        return False, None
    raw = _header_value(headers, REPORTED_COST_HEADER)
    if raw is None:
        return False, None
    return True, _parse_header_cost(raw)


def classify_reported_cost(
    usage: Mapping[str, Any] | None, headers: object = None
) -> CostVerdict:
    """Classify one response's provider-reported cost; unknown is never free.

    Args:
        usage: The response's ``usage`` object (or the final stream usage frame).
        headers: Optional response headers (mapping-like or ``(name, value)`` pairs).

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


def request_has_idempotency_key(request_headers: object) -> bool:
    """Return whether an outbound request carried a non-empty ``Idempotency-Key``.

    Such replies omit ``usage.cost`` by design, so they are no evidence at all.
    """
    value = _header_value(request_headers, IDEMPOTENCY_KEY_HEADER)
    return value is not None and bool(str(value).strip())


def is_free_quota_exhausted_error(status: object, payload: object) -> bool:
    """Return whether a provider error is a 429 free-allowance exhaustion.

    Matches the documented ``insufficient_quota`` / ``free_limit_reached``
    markers in ``error.code``, ``error.type`` or ``error.message``.
    """
    if status != 429 or not isinstance(payload, Mapping):
        return False
    error = payload.get("error")
    fields: list[object] = []
    if isinstance(error, Mapping):
        fields.extend(error.get(key) for key in ("code", "type", "message"))
    elif isinstance(error, str):
        fields.append(error)
    fields.extend(payload.get(key) for key in ("code", "type"))
    for field in fields:
        if isinstance(field, str) and any(
            marker in field.casefold() for marker in FREE_QUOTA_ERROR_MARKERS
        ):
            return True
    return False


def free_promotion_slugs(payload: object) -> frozenset[str]:
    """Return model slugs with an explicit ``free: true`` promotion.

    Reads ``promotions[]`` from the public ``GET /api/models`` response. Only
    ``free is True`` counts (a ``badge_style: "free"`` label does not), and a
    ``display_only`` promotion nominates nothing. Malformed input yields an
    empty set (fail-closed).
    """
    if not isinstance(payload, Mapping):
        return frozenset()
    promotions = payload.get("promotions")
    if not isinstance(promotions, list):
        return frozenset()
    slugs: set[str] = set()
    for promotion in promotions:
        if not isinstance(promotion, Mapping):
            continue
        if promotion.get("free") is not True or promotion.get("display_only") is True:
            continue
        for key in ("slugs", "listed_slugs"):
            values = promotion.get(key)
            if isinstance(values, list):
                slugs.update(
                    value.strip() for value in values if isinstance(value, str) and value.strip()
                )
    return frozenset(slugs)


def last_allowance_reset(now: float) -> float:
    """Return the epoch seconds of the most recent allowance reset boundary.

    The provider resets at 00:00 UTC; the boundary is that midnight plus
    :data:`ALLOWANCE_RESET_SKEW_SECONDS` (00:05 UTC), so ``now`` between 00:00
    and 00:05 UTC still belongs to the previous allowance day.
    """
    day = time.gmtime(now - ALLOWANCE_RESET_SKEW_SECONDS)
    midnight = calendar.timegm((day.tm_year, day.tm_mon, day.tm_mday, 0, 0, 0))
    return float(midnight + ALLOWANCE_RESET_SKEW_SECONDS)


@dataclass(frozen=True)
class CostObservation:
    """The last cost verdict recorded for one route."""

    verdict: CostVerdict
    observed_at: float


class FreeServingLedger:
    """Thread-safe, process-local verdict store keyed by route identity.

    Two facts are kept per route: the last observation (verdict + time) and,
    separately, the time of the last ``PAID``/``EXHAUSTED`` demotion. Keeping
    the demotion apart means a later ``UNKNOWN`` (a failed call, a missing
    cost) can replace the last verdict without erasing the hold.
    """

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._lock = threading.Lock()
        self._observations: dict[tuple[str, str], CostObservation] = {}
        self._demoted_at: dict[tuple[str, str], float] = {}
        self._clock = clock

    def now(self) -> float:
        """Return the ledger clock's current time."""
        return float(self._clock())

    def _demotion_active(self, key: tuple[str, str], now: float) -> bool:
        demoted_at = self._demoted_at.get(key)
        return demoted_at is not None and demoted_at >= last_allowance_reset(now)

    def record(self, provider_name: str, model_id: str, verdict: CostVerdict) -> bool:
        """Record one verdict and return whether it was stored.

        ``UNKNOWN`` is kept only for evidence-required providers: a provider
        that never reports per-call cost would otherwise overwrite a
        meaningful ``PAID`` demotion with noise. For evidence-required
        providers ``UNKNOWN`` replaces an earlier ``FREE`` (fail-closed).

        A ``PAID``/``EXHAUSTED`` demotion holds until the next allowance reset
        after it (:func:`last_allowance_reset`): until then a ``FREE`` verdict
        is rejected, however many other verdicts were recorded in between.
        """
        if not provider_name or not model_id:
            return False
        if (
            verdict is CostVerdict.UNKNOWN
            and provider_name not in COST_EVIDENCE_REQUIRED_PROVIDERS
        ):
            return False
        with self._lock:
            now = self.now()
            key = (provider_name, model_id)
            if verdict is CostVerdict.FREE and self._demotion_active(key, now):
                return False
            if verdict in _DEMOTING_VERDICTS:
                self._demoted_at[key] = now
            self._observations[key] = CostObservation(verdict, now)
            return True

    def observation(self, provider_name: str, model_id: str) -> CostObservation | None:
        """Return the last observation for a route, if any."""
        with self._lock:
            return self._observations.get((provider_name, model_id))

    def verdict(self, provider_name: str, model_id: str) -> CostVerdict | None:
        """Return the last verdict for a route, if any (it may be stale; see :meth:`free_now`)."""
        observation = self.observation(provider_name, model_id)
        return observation.verdict if observation is not None else None

    def demoted(self, provider_name: str, model_id: str) -> bool:
        """Return whether a ``PAID``/``EXHAUSTED`` demotion holds for the route now."""
        with self._lock:
            return self._demotion_active((provider_name, model_id), self.now())

    def free_now(self, provider_name: str, model_id: str) -> bool:
        """Return whether fresh ``FREE`` evidence (since the latest reset) admits the route."""
        with self._lock:
            now = self.now()
            key = (provider_name, model_id)
            observation = self._observations.get(key)
            return (
                observation is not None
                and observation.verdict is CostVerdict.FREE
                and observation.observed_at >= last_allowance_reset(now)
                and not self._demotion_active(key, now)
            )

    def probe_due(self, provider_name: str, model_id: str) -> bool:
        """Return whether a fresh cost probe may run for this route now.

        Never-observed routes are due. Otherwise a route is due only when its
        last observation predates the latest allowance reset: that covers a
        demotion or ``UNKNOWN`` from an earlier allowance day and a ``FREE``
        verdict that expired at the reset. A route observed since the reset is
        not due (a ``FREE`` one keeps being re-checked by served traffic; a
        demoted or unknown one waits for the next reset, so a route is probed
        at most once per allowance day).
        """
        with self._lock:
            now = self.now()
            key = (provider_name, model_id)
            observation = self._observations.get(key)
            if observation is None:
                return True
            if self._demotion_active(key, now):
                return False
            return observation.observed_at < last_allowance_reset(now)

    def claim_probe(self, provider_name: str, model_id: str) -> bool:
        """Atomically reserve one route\'s probe slot for the current allowance day.

        The reservation is an UNKNOWN observation made before network I/O.
        Concurrent schedulers therefore cannot both pass a separate
        probe_due check and issue duplicate, potentially billed probes.
        """
        if not provider_name or not model_id:
            return False
        with self._lock:
            now = self.now()
            key = (provider_name, model_id)
            observation = self._observations.get(key)
            if observation is not None:
                if self._demotion_active(key, now):
                    return False
                if observation.observed_at >= last_allowance_reset(now):
                    return False
            self._observations[key] = CostObservation(CostVerdict.UNKNOWN, now)
            return True

    def snapshot(self) -> dict[str, str]:
        """Return a JSON-safe ``"provider/model" -> verdict`` view for evidence files."""
        with self._lock:
            return {
                f"{provider}/{model}": observation.verdict.value
                for (provider, model), observation in sorted(self._observations.items())
            }

    def reset(self) -> None:
        """Forget every observation and demotion (tests and process-level resets)."""
        with self._lock:
            self._observations.clear()
            self._demoted_at.clear()


FREE_SERVING_LEDGER = FreeServingLedger()
"""Process-wide ledger shared by discovery, preflight, and serving."""


def record_reported_cost(
    provider_name: str | None,
    model_id: str | None,
    usage: Mapping[str, Any] | None,
    headers: object = None,
    *,
    request_headers: object = None,
    ledger: FreeServingLedger | None = None,
) -> CostVerdict | None:
    """Classify one response and record the verdict for its route.

    Returns ``None`` (nothing recorded) for an ``Idempotency-Key`` request.
    """
    if request_has_idempotency_key(request_headers):
        return None
    verdict = classify_reported_cost(usage, headers)
    (ledger or FREE_SERVING_LEDGER).record(provider_name or "", model_id or "", verdict)
    return verdict


def record_provider_error(
    provider_name: str | None,
    model_id: str | None,
    status: object,
    payload: object,
    *,
    request_headers: object = None,
    ledger: FreeServingLedger | None = None,
) -> CostVerdict | None:
    """Record the verdict an HTTP error response implies for its route.

    * A 429 free-quota error is ``EXHAUSTED`` for every provider.
    * For evidence-required providers an HTTP 402 (payment required) is
      ``EXHAUSTED`` as well, and any other error status is ``UNKNOWN``: the
      call did not complete with a parsed cost, so it cannot keep a ``FREE``.
    * Other errors from other providers are ignored.

    Returns the recorded verdict, or ``None`` when nothing was recorded.
    """
    if request_has_idempotency_key(request_headers):
        return None
    provider = provider_name or ""
    if is_free_quota_exhausted_error(status, payload):
        verdict = CostVerdict.EXHAUSTED
    elif provider not in COST_EVIDENCE_REQUIRED_PROVIDERS:
        return None
    elif status == PAYMENT_REQUIRED_STATUS:
        verdict = CostVerdict.EXHAUSTED
    else:
        verdict = CostVerdict.UNKNOWN
    (ledger or FREE_SERVING_LEDGER).record(provider, model_id or "", verdict)
    return verdict


def record_failed_call(
    provider_name: str | None,
    model_id: str | None,
    *,
    request_headers: object = None,
    ledger: FreeServingLedger | None = None,
) -> CostVerdict | None:
    """Record ``UNKNOWN`` for an evidence-required call that produced no parsed cost.

    Used for transport errors, unreadable or truncated bodies, and streams that
    raised or were abandoned before the final usage frame. Other providers
    are unaffected. Returns the recorded verdict, or ``None``.
    """
    if request_has_idempotency_key(request_headers):
        return None
    if (provider_name or "") not in COST_EVIDENCE_REQUIRED_PROVIDERS:
        return None
    (ledger or FREE_SERVING_LEDGER).record(
        provider_name or "", model_id or "", CostVerdict.UNKNOWN
    )
    return CostVerdict.UNKNOWN


def free_serving_admitted(
    provider_name: str | None,
    model_id: str | None,
    *,
    catalog_free: bool,
    ledger: FreeServingLedger | None = None,
) -> bool:
    """Return whether a route may serve a free selector right now.

    * Evidence-required providers: only a ``FREE`` verdict recorded since the
      latest allowance reset, with no demotion held since then.
    * Every other provider: catalog-free, last verdict not ``PAID``/``EXHAUSTED``,
      and no demotion held since the latest reset.
    """
    store = ledger or FREE_SERVING_LEDGER
    provider = provider_name or ""
    model = model_id or ""
    if provider in COST_EVIDENCE_REQUIRED_PROVIDERS:
        return store.free_now(provider, model)
    return (
        bool(catalog_free)
        and store.verdict(provider, model) not in _DEMOTING_VERDICTS
        and not store.demoted(provider, model)
    )


def is_free_nominated(model: object) -> bool:
    """Return whether catalog evidence nominates a discovered row as a free candidate."""
    return bool(getattr(model, "is_free", False)) or bool(
        getattr(model, "free_promotion", False)
    )


def probe_free_candidates(
    models: Iterable[object],
    *,
    probe: Callable[[object], object],
    max_probes: int,
    ledger: FreeServingLedger | None = None,
) -> dict[str, object]:
    """Send at most ``max_probes`` cost probes to nominated, probe-due routes.

    Only evidence-required providers are probed (other providers are admitted
    from catalog price). ``probe`` must send one real request through
    :class:`~contextual_orchestrator.orchestrator.ModelClient`, which records
    the response's verdict (or ``EXHAUSTED`` for a 429 free-quota error). A
    probe that fails without recording anything records ``UNKNOWN``.

    Returns:
        ``{"probes": n, "probed": ["provider/model", ...]}``.
    """
    store = ledger or FREE_SERVING_LEDGER
    probed: list[str] = []
    for model in models:
        if len(probed) >= max_probes:
            break
        provider = str(getattr(model, "provider_name", "") or "")
        model_id = str(getattr(model, "model_id", "") or "")
        if (
            provider not in COST_EVIDENCE_REQUIRED_PROVIDERS
            or not is_free_nominated(model)
            or not store.claim_probe(provider, model_id)
        ):
            continue
        probed.append(f"{provider}/{model_id}")
        before = store.observation(provider, model_id)
        try:
            probe(model)
        except Exception:  # noqa: BLE001 - any failure is "not proven free"
            if store.observation(provider, model_id) is before:
                store.record(provider, model_id, CostVerdict.UNKNOWN)
            continue
        if store.observation(provider, model_id) is before:
            # The probe path recorded nothing (e.g. a mock transport).
            store.record(provider, model_id, CostVerdict.UNKNOWN)
    return {"probes": len(probed), "probed": probed}
