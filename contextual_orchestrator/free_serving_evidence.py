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
  cost (:func:`classify_reported_cost`): ``cost == 0`` with an explicit
  ``is_byok: false`` is ``FREE``; ``cost > 0`` is ``PAID``; anything missing,
  malformed, negative, non-finite, or BYOK is ``UNKNOWN``. A 429
  ``insufficient_quota`` / ``free_limit_reached`` error is ``EXHAUSTED``
  (:func:`is_free_quota_exhausted_error`). Requests sent with an
  ``Idempotency-Key`` carry no cost and are skipped entirely: they neither
  promote nor demote (:func:`request_has_idempotency_key`).
* **Ledger.** :data:`FREE_SERVING_LEDGER` keeps the last verdict per
  ``(provider, model)`` for this process. ``PAID`` and ``EXHAUSTED`` demote the
  route out of every free selector immediately, and the demotion holds until
  the next 00:00 UTC allowance reset (09:00 KST).
* **Admission.** :func:`free_serving_admitted` is the one predicate
  discovery-time selection (``model_discovery.general_free_serving_candidates``)
  and serving-time selection (``TaskOrchestrator._is_free_agent``) share, so
  the two cannot disagree and leave a dead route occupying a free slot.
  Providers in :data:`COST_EVIDENCE_REQUIRED_PROVIDERS` are fail-closed:
  without a ``FREE`` verdict they are paid, whatever the catalog says. Other
  providers keep catalog-price admission and are only demoted by explicit
  ``PAID``/``EXHAUSTED`` evidence.
* **Re-admission.** A demoted route becomes *probe-due* again after the next
  00:00 UTC free-allowance reset (:meth:`FreeServingLedger.probe_due`). It is
  re-admitted only by fresh ``FREE`` evidence from that probe, never assumed
  free (:func:`probe_free_candidates`).

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
"""

from __future__ import annotations

import calendar
import enum
import math
import threading
import time
from collections.abc import Callable, Iterable, Mapping
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


class CostVerdict(str, enum.Enum):
    """Classification of one provider response's reported cost."""

    FREE = "free"
    PAID = "paid"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


_DEMOTING_VERDICTS = frozenset({CostVerdict.PAID, CostVerdict.EXHAUSTED})


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
    return True, _parse_cost(raw)


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
    """Return the epoch seconds of the most recent 00:00 UTC (free-tier reset)."""
    day = time.gmtime(now)
    return float(calendar.timegm((day.tm_year, day.tm_mon, day.tm_mday, 0, 0, 0)))


@dataclass(frozen=True)
class CostObservation:
    """The last cost verdict recorded for one route."""

    verdict: CostVerdict
    observed_at: float


class FreeServingLedger:
    """Thread-safe, process-local last-verdict store keyed by route identity."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._lock = threading.Lock()
        self._observations: dict[tuple[str, str], CostObservation] = {}
        self._clock = clock

    def now(self) -> float:
        """Return the ledger clock's current time."""
        return float(self._clock())

    def record(self, provider_name: str, model_id: str, verdict: CostVerdict) -> None:
        """Record one verdict; ``UNKNOWN`` is kept only for evidence-required providers.

        A provider that never reports per-call cost would otherwise overwrite
        a meaningful ``PAID`` demotion with noise. For evidence-required
        providers ``UNKNOWN`` replaces an earlier ``FREE`` (fail-closed).

        A ``PAID``/``EXHAUSTED`` demotion holds until the next 00:00 UTC
        allowance reset: a ``FREE`` verdict observed before that reset is
        ignored, so a demoted route is re-admitted only by fresh ``FREE``
        evidence gathered after the reset.
        """
        if not provider_name or not model_id:
            return
        if (
            verdict is CostVerdict.UNKNOWN
            and provider_name not in COST_EVIDENCE_REQUIRED_PROVIDERS
        ):
            return
        with self._lock:
            now = self.now()
            key = (provider_name, model_id)
            current = self._observations.get(key)
            if (
                verdict is CostVerdict.FREE
                and current is not None
                and current.verdict in _DEMOTING_VERDICTS
                and current.observed_at >= last_allowance_reset(now)
            ):
                return
            self._observations[key] = CostObservation(verdict, now)

    def observation(self, provider_name: str, model_id: str) -> CostObservation | None:
        """Return the last observation for a route, if any."""
        with self._lock:
            return self._observations.get((provider_name, model_id))

    def verdict(self, provider_name: str, model_id: str) -> CostVerdict | None:
        """Return the last verdict for a route, if any."""
        observation = self.observation(provider_name, model_id)
        return observation.verdict if observation is not None else None

    def probe_due(self, provider_name: str, model_id: str) -> bool:
        """Return whether a fresh cost probe may run for this route now.

        Never-observed routes are due. A ``FREE`` route is not (served traffic
        keeps re-checking it). A non-``FREE`` route becomes due again only after
        the next 00:00 UTC allowance reset following its observation; until a
        probe returns ``FREE`` it stays out of every free selector.
        """
        observation = self.observation(provider_name, model_id)
        if observation is None:
            return True
        if observation.verdict is CostVerdict.FREE:
            return False
        return observation.observed_at < last_allowance_reset(self.now())

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
    """Record ``EXHAUSTED`` for a 429 free-quota error; ignore any other error."""
    if request_has_idempotency_key(request_headers):
        return None
    if not is_free_quota_exhausted_error(status, payload):
        return None
    (ledger or FREE_SERVING_LEDGER).record(
        provider_name or "", model_id or "", CostVerdict.EXHAUSTED
    )
    return CostVerdict.EXHAUSTED


def free_serving_admitted(
    provider_name: str | None,
    model_id: str | None,
    *,
    catalog_free: bool,
    ledger: FreeServingLedger | None = None,
) -> bool:
    """Return whether a route may serve a free selector right now.

    * Evidence-required providers: only a last verdict of ``FREE``.
    * Every other provider: catalog-free and not demoted by ``PAID``/``EXHAUSTED``.
    """
    verdict = (ledger or FREE_SERVING_LEDGER).verdict(provider_name or "", model_id or "")
    if (provider_name or "") in COST_EVIDENCE_REQUIRED_PROVIDERS:
        return verdict is CostVerdict.FREE
    return bool(catalog_free) and verdict not in _DEMOTING_VERDICTS


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
            or not store.probe_due(provider, model_id)
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
