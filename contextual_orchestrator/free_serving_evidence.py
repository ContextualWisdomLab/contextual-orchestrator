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
  with an ``Idempotency-Key`` carry no cost, so cost-dependent evidence is
  skipped. Explicit quota-exhaustion and payment-required errors still demote
  because their authority does not depend on ``usage.cost``
  (:func:`request_has_idempotency_key`).
* **Ledger.** :data:`FREE_SERVING_LEDGER` keeps the last verdict per
  ``(provider, model)`` for this process. ``PAID`` and ``EXHAUSTED`` demote
  the route out of every free selector immediately. A provider calendar is
  not pre-send entitlement evidence, so the demotion persists until an
  explicit process-level reset; later ``UNKNOWN`` or ``FREE`` observations
  cannot clear it.
* **Admission.** :func:`free_serving_admitted` is the one predicate
  discovery-time selection (``model_discovery.general_free_serving_candidates``)
  and serving-time selection (``TaskOrchestrator._is_free_agent``) share, so
  the two cannot disagree and leave a dead route occupying a free slot.
  Providers in :data:`COST_EVIDENCE_REQUIRED_PROVIDERS` are fail-closed:
  post-response cost cannot prove the next call is free, so they remain paid
  until an authoritative pre-send entitlement exists. Other providers keep
  catalog-price admission and are only demoted by explicit
  ``PAID``/``EXHAUSTED`` evidence.
* **No paid probe.** :func:`probe_free_candidates` preserves its public return
  shape but sends no request. A possibly billed request cannot establish the
  precondition that the request is free.

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

Known limitation: the provider currently exposes cost only after a request.
Evidence-required routes therefore stay outside ``orchestrator/free`` until
the provider publishes an authoritative pre-send entitlement API.
"""

from __future__ import annotations

import enum
import hashlib
import math
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

COST_EVIDENCE_REQUIRED_PROVIDERS: frozenset[str] = frozenset({"experiential_labs"})
"""Providers requiring authoritative pre-send evidence for free admission.

Post-response cost and catalog promotions are observational only; neither
proves that the next request is free.
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


def credential_route_identity(
    provider_name: str, credential_name: str, endpoint_url: str
) -> str:
    """Return a secret-free identity for one credential and provider endpoint.

    The credential name and endpoint, never the credential value, distinguish
    accounts that expose the same provider/model pair. A short digest keeps
    evidence snapshots free of credential labels and URLs.
    """
    provider = provider_name.strip()
    if not provider:
        return ""
    material = f"{credential_name.strip()}\\0{endpoint_url.strip().rstrip('/')}"
    fingerprint = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"{provider}:credential_route:{fingerprint}"

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

    def _demotion_active(self, key: tuple[str, str]) -> bool:
        """Return whether an explicit demotion remains uncleared.

        A provider calendar is not pre-send entitlement evidence. Demotions
        therefore persist until an explicit process-level reset.
        """
        return key in self._demoted_at

    def record(
        self,
        provider_name: str,
        model_id: str,
        verdict: CostVerdict,
        *,
        route_identity: str | None = None,
    ) -> bool:
        """Record one verdict and return whether it was stored.

        ``UNKNOWN`` is kept only for evidence-required providers: a provider
        that never reports per-call cost would otherwise overwrite a
        meaningful ``PAID`` demotion with noise. For evidence-required
        providers ``UNKNOWN`` replaces an earlier ``FREE`` (fail-closed).

        A ``PAID``/``EXHAUSTED`` demotion persists until an explicit
        process-level reset. A later ``FREE`` verdict is rejected.
        """
        identity = route_identity or provider_name
        if not provider_name or not identity or not model_id:
            return False
        if (
            verdict is CostVerdict.UNKNOWN
            and provider_name not in COST_EVIDENCE_REQUIRED_PROVIDERS
        ):
            return False
        with self._lock:
            now = self.now()
            key = (identity, model_id)
            if verdict is CostVerdict.FREE and self._demotion_active(key):
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
        """Return whether a ``PAID``/``EXHAUSTED`` demotion remains uncleared."""
        with self._lock:
            return self._demotion_active((provider_name, model_id))

    def free_now(self, provider_name: str, model_id: str) -> bool:
        """Return whether the last observation is FREE and no demotion persists.

        This is an observational query, not pre-send admission authority.
        """
        with self._lock:
            key = (provider_name, model_id)
            observation = self._observations.get(key)
            return (
                observation is not None
                and observation.verdict is CostVerdict.FREE
                and not self._demotion_active(key)
            )

    def probe_due(self, provider_name: str, model_id: str) -> bool:
        """Return False because post-hoc cost probes are not free-pool authority."""
        return False

    def claim_probe(self, provider_name: str, model_id: str) -> bool:
        """Return False because the free pool never sends a cost probe."""
        return False

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
    route_identity: str | None = None,
) -> CostVerdict | None:
    """Classify one response and record the verdict for its route.

    Returns ``None`` (nothing recorded) for an ``Idempotency-Key`` request.
    """
    if request_has_idempotency_key(request_headers):
        return None
    verdict = classify_reported_cost(usage, headers)
    (ledger or FREE_SERVING_LEDGER).record(
        provider_name or "", model_id or "", verdict, route_identity=route_identity
    )
    return verdict


def record_provider_error(
    provider_name: str | None,
    model_id: str | None,
    status: object,
    payload: object,
    *,
    request_headers: object = None,
    ledger: FreeServingLedger | None = None,
    route_identity: str | None = None,
) -> CostVerdict | None:
    """Record the verdict an HTTP error response implies for its route.

    * A 429 free-quota error is ``EXHAUSTED`` for every provider.
    * For evidence-required providers an HTTP 402 (payment required) is
      ``EXHAUSTED`` as well, and any other error status is ``UNKNOWN``: the
      call did not complete with a parsed cost, so it cannot keep a ``FREE``.
    * Other errors from other providers are ignored.

    ``Idempotency-Key`` suppresses only cost-dependent error evidence.
    Explicit quota-exhaustion and payment-required errors remain authoritative.

    Returns the recorded verdict, or ``None`` when nothing was recorded.
    """
    provider = provider_name or ""
    if is_free_quota_exhausted_error(status, payload):
        verdict = CostVerdict.EXHAUSTED
    elif (
        provider in COST_EVIDENCE_REQUIRED_PROVIDERS
        and status == PAYMENT_REQUIRED_STATUS
    ):
        verdict = CostVerdict.EXHAUSTED
    elif request_has_idempotency_key(request_headers):
        return None
    elif provider not in COST_EVIDENCE_REQUIRED_PROVIDERS:
        return None
    else:
        verdict = CostVerdict.UNKNOWN
    (ledger or FREE_SERVING_LEDGER).record(
        provider, model_id or "", verdict, route_identity=route_identity
    )
    return verdict


def record_failed_call(
    provider_name: str | None,
    model_id: str | None,
    *,
    request_headers: object = None,
    ledger: FreeServingLedger | None = None,
    route_identity: str | None = None,
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
        provider_name or "",
        model_id or "",
        CostVerdict.UNKNOWN,
        route_identity=route_identity,
    )
    return CostVerdict.UNKNOWN


def free_serving_admitted(
    provider_name: str | None,
    model_id: str | None,
    *,
    catalog_free: bool,
    ledger: FreeServingLedger | None = None,
    route_identity: str | None = None,
) -> bool:
    """Return whether a route may serve a free selector right now.

    Evidence-required providers remain closed until an authoritative pre-send
    entitlement exists. Every other provider is catalog-free, has no demoting
    verdict, and has no persistent demotion.
    """
    store = ledger or FREE_SERVING_LEDGER
    provider = provider_name or ""
    model = model_id or ""
    identity = route_identity or provider
    if provider in COST_EVIDENCE_REQUIRED_PROVIDERS:
        return False
    return (
        bool(catalog_free)
        and store.verdict(identity, model) not in _DEMOTING_VERDICTS
        and not store.demoted(identity, model)
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
    """Return a zero-probe receipt without invoking the network callback.

    Post-response cost cannot authorize the request that produced it. The
    parameters remain for API compatibility until a versioned pre-send
    entitlement contract replaces this function.
    """
    del models, probe, max_probes, ledger
    return {"probes": 0, "probed": []}
