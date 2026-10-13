"""Spend guard: per-run cap, virtual-key and tenant budgets, provider drop.

This is the application service around the pure rules in
:mod:`contextual_orchestrator.domain`. One :class:`SpendGuard` belongs to a
``TaskOrchestrator``; every top-level run (``complete``, ``run``,
``route_once``, ``conduct``, ``stream_route``, ``proxy_completion``,
``compare_to_baseline``) opens a :class:`RunSpendScope` held in a
:class:`contextvars.ContextVar`, so concurrent server requests never share a
run budget and worker threads started with ``copy_context`` see their run.

``ModelClient`` routes every paid provider send through one of these hooks:

* :func:`guarded_provider_call` / :func:`guarded_provider_stream` for chat,
  streamed chat, and the capability ``probe``: refuse a call to a provider
  already dropped in this run, refuse a call no active budget can afford
  (reservation of the admission bound, tightest limit wins, 50% baseline
  headroom rule), pin the sent ``max_tokens`` to the bound
  (:func:`enforce_admitted_output_cap`), then meter the call and classify a
  limit-exhaustion error (drop that provider).
* :func:`metered_passthrough_call` for passthrough, binary, embeddings, and
  Batch API calls: the same admission, with the bound derived from the request
  body (:func:`passthrough_token_bounds`) or supplied by the caller.
* :func:`raise_if_stream_limit_event` for an error object arriving inside a
  streamed HTTP 200 response.

A call whose outcome is unknown (timeout, dropped connection, no usage)
counts at its admission bound and marks the run's measurement incomplete;
a failure raised before provider egress (:func:`declare_pre_egress` /
:func:`mark_provider_egress`) provably cost nothing.

"Per run" means the outermost scope: a nested decorated entry point, a
nested :meth:`SpendGuard.run_scope`, and an implicit scope all join an
already-active scope (same run id, cap, and ledger), so a caller can wrap a
whole session in one ``run_scope`` to share one cap. A paid call made with no
active scope runs in an implicit single-call scope of the client's guard
(recorded, see :meth:`SpendGuard.last_implicit_run_summary`); only a
``ModelClient`` with no guard attached passes through unmetered. See ADR 0138.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal
import logging
import secrets
import threading
import time
import urllib.error
import uuid
from typing import Any, Callable, Iterator, TypeVar

from .cost_ledger import CostLedger, PriceBook, UsageRecord
from .domain.budget import (
    DEFAULT_BASELINE_MIN_REMAINING_RATIO,
    AffordabilityDecision,
    BudgetExceededError,
    BudgetScope,
    CallPurpose,
    SpendLimit,
    SpendPosition,
    decide_affordability,
    parse_budget_duration,
)
from .domain.money import Money, Price, Usage, provider_reported_cost, to_decimal
from .domain.pricing import (
    AdmissionTokenBounds,
    effective_price,
    estimate_call_cost,
    estimate_request_cost,
)
from .domain.provider_limits import (
    NOT_A_LIMIT,
    ProviderLimitAction,
    ProviderLimitSignal,
    classify_provider_limit,
    limit_evidence_from_payload,
)
from .domain.tenancy import (
    DEFAULT_TENANT_ID,
    TenantBudget,
    VirtualKey,
    hash_virtual_key,
    validate_tenant_id,
)
from .kv_config import InMemoryConfigStore
from .provider_errors import ProviderUpstreamError, provider_limit_evidence
from .spend_metering import (
    MeteredUsage,
    SpendLedgerStore,
    SpendReservation,
    reserved_in_scope,
    settled_in_scope,
    spent_in_scope,
    summarize_run,
)

LOGGER = logging.getLogger(__name__)

#: KV config category read by :meth:`SpendGuardConfig.from_config_store`.
SPEND_GUARD_CONFIG_CATEGORY = "spend_guard_settings"

#: Caller-facing error code when every remaining call would hit a dropped provider.
PROVIDER_BUDGET_EXHAUSTED_CODE = "provider_budget_exhausted"

T = TypeVar("T")

_ACTIVE_RUN: ContextVar["RunSpendScope | None"] = ContextVar("spend_guard_active_run", default=None)
_PENDING_IDENTITY: ContextVar["_Identity | None"] = ContextVar(
    "spend_guard_pending_identity", default=None
)
_CALL_PURPOSE: ContextVar[CallPurpose] = ContextVar(
    "spend_guard_call_purpose", default=CallPurpose.PRIMARY
)
#: Output-token total the current call's admission bound assumed (narrow bound
#: only); the transport must not send a larger ``max_tokens``.
_ADMITTED_OUTPUT_TOKENS: ContextVar[int | None] = ContextVar(
    "spend_guard_admitted_output_tokens", default=None
)


class _EgressState:
    """Whether the current guarded call's transport reached provider egress.

    A transport that calls :func:`declare_pre_egress` at its start and
    :func:`mark_provider_egress` immediately before handing the request to the
    network is *instrumented*: a failure raised before the mark (missing
    credential, local validation, a refused destination) provably sent
    nothing and costs zero. An uninstrumented transport (a fake, a patched
    sender) stays unknown, so its failure counts at the admission bound.
    """

    __slots__ = ("instrumented", "sent")

    def __init__(self) -> None:
        self.instrumented = False
        self.sent = False

    @property
    def provably_not_sent(self) -> bool:
        """True when an instrumented transport failed before provider egress."""
        return self.instrumented and not self.sent


_EGRESS: ContextVar[_EgressState | None] = ContextVar("spend_guard_egress", default=None)

#: Request-body keys that do not add billed prompt tokens beyond ``messages``
#: and ``tools`` (both counted by the exact counter) and whose output is capped
#: by ``max_tokens``/``max_completion_tokens``. Any other key (for example
#: ``response_format``, ``reasoning``, ``plugins``, ``web_search_options``,
#: ``prediction``, ``audio``) makes the prompt count non-authoritative, so
#: admission falls back to the context-window ceiling.
_PROMPT_NEUTRAL_KEYS = frozenset(
    {
        "model",
        "messages",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "max_tokens",
        "max_completion_tokens",
        "temperature",
        "top_p",
        "n",
        "stream",
        "stream_options",
        "stop",
        "seed",
        "presence_penalty",
        "frequency_penalty",
        "logit_bias",
        "logprobs",
        "top_logprobs",
        "user",
        "metadata",
        "reasoning_effort",
        "provider",
        "chat_template_kwargs",
    }
)


class VirtualKeyError(PermissionError):
    """A presented virtual key is unknown, disabled, or inconsistent with the tenant."""


class ProviderBudgetExhaustedError(ProviderUpstreamError):
    """A provider reported (now or earlier in this run) that its budget is exhausted.

    Non-retryable, so the orchestrator's existing failover moves to the next
    candidate; when no other provider remains, this is the final error.
    """


@dataclass(frozen=True)
class SpendGuardConfig:
    """Operator configuration for the per-run cap.

    ``run_max_cost`` defaults to ``None``: no per-run cap, so existing
    deployments keep their behavior until an operator sets one (CLI
    ``--run-max-cost-usd`` or KV ``spend_guard_settings/run_max_cost_usd``).
    ``baseline_min_remaining_ratio`` defaults to 0.5: under a hard cap a paid
    sampled baseline runs only while at least half of every applicable cap
    (run, virtual key, tenant) would remain after the call, priced at its
    total-cost upper bound. Zero-cost baselines are not subject to the ratio.
    """

    run_max_cost: Money | None = None
    baseline_min_remaining_ratio: Decimal = DEFAULT_BASELINE_MIN_REMAINING_RATIO

    def __post_init__(self) -> None:
        """Validate the ratio range."""
        ratio = to_decimal(self.baseline_min_remaining_ratio)
        if ratio > 1:
            raise ValueError("baseline_min_remaining_ratio must be within [0, 1]")
        object.__setattr__(self, "baseline_min_remaining_ratio", ratio)

    @classmethod
    def from_values(
        cls,
        *,
        run_max_cost_usd: object | None = None,
        baseline_min_remaining_ratio: object | None = None,
    ) -> "SpendGuardConfig":
        """Build a config from plain numbers (``None`` keeps the default)."""
        return cls(
            run_max_cost=None if run_max_cost_usd is None else Money.usd(run_max_cost_usd),
            baseline_min_remaining_ratio=(
                DEFAULT_BASELINE_MIN_REMAINING_RATIO
                if baseline_min_remaining_ratio is None
                else to_decimal(baseline_min_remaining_ratio)
            ),
        )

    @classmethod
    def from_config_store(cls, store: Any) -> "SpendGuardConfig":
        """Read ``run_max_cost_usd`` and ``baseline_min_remaining_ratio`` from the KV store."""
        return cls.from_values(
            run_max_cost_usd=store.get(SPEND_GUARD_CONFIG_CATEGORY, "run_max_cost_usd", None),
            baseline_min_remaining_ratio=store.get(
                SPEND_GUARD_CONFIG_CATEGORY, "baseline_min_remaining_ratio", None
            ),
        )


class PriceBookCatalog:
    """:class:`~contextual_orchestrator.domain.pricing.PriceCatalog` over ``cost_ledger.PriceBook``."""

    def __init__(self, price_book: PriceBook) -> None:
        self.price_book = price_book

    def price_for(self, provider: str, model: str) -> Price | None:
        """Return the PriceBook row (or provider wildcard) as a domain price."""
        entry = self.price_book.get_price(provider, model)
        return None if entry is None else Price.from_price_entry(entry)


class _DiscardingLedgerStore:
    """Ledger store for the guard's own ``CostLedger``: persistence is the spend store."""

    def append(self, record: UsageRecord) -> bool:
        """Accept and discard (durable rows go to the ``SpendLedgerStore``)."""
        return True

    def query(self, start: int | None = None, end: int | None = None) -> list[dict[str, Any]]:
        """Return nothing; query the ``SpendLedgerStore`` instead."""
        return []


@dataclass(frozen=True)
class _Identity:
    tenant_id: str
    virtual_key: VirtualKey | None


def _error_status_and_evidence(exc: BaseException) -> tuple[int | None, dict[str, str]]:
    if isinstance(exc, ProviderUpstreamError):
        return exc.provider_status, dict(getattr(exc, "limit_evidence", {}) or {})
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code, provider_limit_evidence(exc)
    return None, {}


@dataclass(frozen=True)
class Admission:
    """The outcome of one admitted provider call.

    ``estimate`` is the proved cost upper bound (``None`` when unknown and no
    hard cap required one); ``output_cap`` is the output-token total that
    bound assumed, set only when the narrow prompt + max-output bound was
    used, so the transport can verify the ``max_tokens`` it actually sends.
    """

    price: Price | None
    reservation: SpendReservation | None
    estimate: Money | None
    estimate_source: str | None
    output_cap: int | None = None


class RunSpendScope:
    """Budget, dropped providers, and metered calls for one run (thread-safe)."""

    def __init__(
        self,
        guard: "SpendGuard",
        *,
        run_id: str,
        tenant_id: str,
        virtual_key: VirtualKey | None,
    ) -> None:
        self.guard = guard
        self.run_id = run_id
        self.tenant_id = tenant_id
        self.virtual_key = virtual_key
        self._lock = threading.RLock()
        currency = guard.config.run_max_cost.currency if guard.config.run_max_cost else "USD"
        self.spent = Money.zero(currency)
        self.reserved = Money.zero(currency)
        self.measurement_complete = True
        self.dropped_providers: dict[str, str] = {}
        self.entries: list[MeteredUsage] = []
        self.refusals: list[dict[str, Any]] = []
        self.store_failures = 0
        self._soft_alerts: set[str] = set()
        #: In-run provider failures whose cost stayed unknown, newest last.
        self.unmeasured_failures: list[dict[str, Any]] = []
        self._last_unmeasured_error: BaseException | None = None
        #: Calls whose actual charge exceeded the admission bound.
        self.bound_overruns: list[dict[str, Any]] = []
        #: Transport payloads whose output cap was lowered to the admitted bound.
        self.output_cap_clamps: list[dict[str, Any]] = []
        #: True for an implicit single-call scope opened by a guard hook.
        self.implicit = False

    # -- budget -------------------------------------------------------------
    def positions(self, now: int) -> list[SpendPosition]:
        """Every active limit with the spend charged against it in its current period."""
        positions: list[SpendPosition] = []
        cap = self.guard.config.run_max_cost
        with self._lock:
            if cap is not None:
                positions.append(
                    SpendPosition(
                        SpendLimit(BudgetScope.RUN, self.run_id, cap),
                        self.spent + self.reserved,
                        self.measurement_complete,
                    )
                )
        store = self.guard.store
        limits: list[SpendLimit] = []
        if self.virtual_key is not None:
            limits.append(self.virtual_key.spend_limit())
        if store is not None:
            tenant_budget = store.tenant_budget(self.tenant_id)
            if tenant_budget is not None:
                limits.append(tenant_budget.spend_limit())
        for limit in limits:
            if limit.max_cost is None and limit.soft_max_cost is None:
                continue
            currency = (limit.max_cost or limit.soft_max_cost).currency  # type: ignore[union-attr]
            since = limit.window_start(now)
            settlements = store.spend_settlements() if store is not None else {}
            spent, _unpriced = spent_in_scope(
                store.usage_entries() if store is not None else self.entries,
                scope=limit.scope,
                scope_id=limit.scope_id,
                since=since,
                currency=currency,
                settled_reservation_ids=settlements.keys(),
            )
            if store is not None:
                # Windowed budgets drop reservations (and unknown entries)
                # made before the current period: an unknown outcome expires
                # with its budget window. All-time budgets keep both until an
                # operator settlement (ADR 0138).
                spent = spent + reserved_in_scope(
                    store.active_spend_reservations(),
                    scope=limit.scope,
                    scope_id=limit.scope_id,
                    since=since,
                    currency=currency,
                )
                spent = spent + settled_in_scope(
                    settlements,
                    scope=limit.scope,
                    scope_id=limit.scope_id,
                    since=since,
                    currency=currency,
                )
            positions.append(SpendPosition(limit, spent, _unpriced == 0))
        return positions

    def decide(
        self,
        estimate: Money | None,
        purpose: CallPurpose,
        *,
        unknown_estimate_reason: str = "price_unknown",
    ) -> AffordabilityDecision:
        """Check one prospective call against every active limit."""
        now = self.guard.now()
        decision = decide_affordability(
            self.positions(now),
            estimate=estimate,
            now=now,
            purpose=purpose,
            unknown_estimate_reason=unknown_estimate_reason,
            baseline_min_remaining_ratio=self.guard.config.baseline_min_remaining_ratio,
        )
        for crossed in decision.soft_budget_crossed:
            if crossed not in self._soft_alerts:
                self._soft_alerts.add(crossed)
                LOGGER.warning("spend soft budget crossed: %s", crossed)
        return decision

    def baseline_admissible(self) -> bool:
        """Whether a sampled baseline comparison may still start in this run.

        This pre-check uses a zero estimate, so it only rules out exhausted
        budgets; the headroom ratio for a paid baseline is enforced in
        :meth:`admit` against the call's total-cost upper bound, and a refusal
        is recorded with reason ``baseline_headroom_exhausted``.
        """
        return self.decide(Money.zero(self.spent.currency), CallPurpose.BASELINE).allowed

    def baseline_skip_reason(self) -> str | None:
        """``None`` when a baseline may start, else the refusal reason to record."""
        decision = self.decide(Money.zero(self.spent.currency), CallPurpose.BASELINE)
        return None if decision.allowed else (decision.reason or "spend_budget")

    def raise_if_exhausted(self) -> None:
        """Raise ``BudgetExceededError`` when any active budget is already exhausted."""
        self.decide(Money.zero(self.spent.currency), CallPurpose.PRIMARY).raise_if_refused()

    def admit(
        self,
        agent: Any,
        messages: Any,
        *,
        token_bounds: AdmissionTokenBounds | None = None,
    ) -> tuple[Price | None, SpendReservation | None]:
        """Atomically reserve an affordable call's cost upper bound and return it with price."""
        admission = self.admit_call(agent, token_bounds=token_bounds)
        return admission.price, admission.reservation

    def admit_call(
        self,
        agent: Any,
        *,
        token_bounds: AdmissionTokenBounds | None = None,
        channel: str = "sync",
    ) -> Admission:
        """Atomically reserve an affordable call's cost upper bound (ADR 0138).

        The bound is ``prompt_tokens x prompt price + max_output_tokens x
        completion price`` when ``token_bounds`` proves both, else the
        ``context_window`` ceiling priced at the costlier rate. With neither,
        a priced call fails closed as ``missing_context_window``.
        """
        provider = str(getattr(agent, "provider_name", "") or "")
        with self._lock:
            reason = self.dropped_providers.get(provider) if provider else None
        if reason is not None:
            raise self._provider_exhausted(agent, reason, provider_status=None)
        price = effective_price(
            self.guard.catalog,
            provider=provider,
            model=str(getattr(agent, "model", "")),
            base_url=str(getattr(agent, "base_url", "")),
            tags=tuple(getattr(agent, "tags", ()) or ()),
        )
        total_token_ceiling = getattr(agent, "context_window", None)
        bounds = token_bounds if isinstance(token_bounds, AdmissionTokenBounds) else None
        has_ceiling = type(total_token_ceiling) is int and total_token_ceiling > 0
        ceiling_calls = bounds.ceiling_multiplier() if bounds is not None else 1
        estimate_source: str | None = None
        output_cap: int | None = None
        if price is None:
            estimate = None
            unknown_estimate_reason = "price_unknown"
        elif price.is_free:
            estimate = Money.zero(price.currency)
            unknown_estimate_reason = "price_unknown"
            estimate_source = "zero_cost"
        elif bounds is not None and bounds.usable():
            estimate = estimate_request_cost(
                price, bounds.prompt_tokens or 0, bounds.max_output_tokens or 0
            )
            estimate_source = "prompt_and_max_output"
            output_cap = bounds.max_output_tokens
            if has_ceiling:
                ceiling = estimate_call_cost(price, total_token_ceiling * ceiling_calls)
                if ceiling is not None and estimate is not None and ceiling < estimate:
                    estimate, estimate_source = ceiling, "context_window_ceiling"
                    output_cap = None
            unknown_estimate_reason = "price_unknown"
        elif has_ceiling:
            estimate = estimate_call_cost(price, total_token_ceiling * ceiling_calls)
            unknown_estimate_reason = "price_unknown"
            estimate_source = "context_window_ceiling"
        else:
            # Fail closed: a priced route without a positive provider context
            # window has no total-cost upper bound. The specific reason is
            # recorded in the refusal (run usage summary budget.refusals).
            estimate = None
            unknown_estimate_reason = "missing_context_window"
        purpose = _CALL_PURPOSE.get()
        store = self.guard.store
        transaction = store.budget_transaction() if store is not None else nullcontext()
        with self._lock, transaction:
            now = self.guard.now()
            positions = self.positions(now)
            hard_positions = [
                position for position in positions if position.limit.max_cost is not None
            ]
            has_hard_cap = bool(hard_positions)
            decision = self.decide(
                estimate,
                purpose,
                unknown_estimate_reason=unknown_estimate_reason,
            )
            shared_hard_position = next(
                (
                    position
                    for position in hard_positions
                    if position.limit.scope is not BudgetScope.RUN
                ),
                None,
            )
            if (
                decision.allowed
                and estimate is not None
                and estimate.amount > 0
                and store is not None
                and shared_hard_position is not None
                and not store.budget_transaction_authoritative
            ):
                decision = decide_affordability(
                    [shared_hard_position],
                    estimate=None,
                    now=now,
                    purpose=purpose,
                    unknown_estimate_reason="reservation_authority_unavailable",
                )
            reservation = (
                SpendReservation(
                    reservation_id=f"spend_reservation_{secrets.token_hex(16)}",
                    tenant_id=self.tenant_id,
                    virtual_key_id=(self.virtual_key.key_id if self.virtual_key else None),
                    run_id=self.run_id,
                    reserved_cost=estimate,
                    created_at=now,
                )
                if decision.allowed
                and has_hard_cap
                and estimate is not None
                and estimate.amount > 0
                else None
            )
            if reservation is not None:
                if store is not None:
                    store.put_spend_reservation(reservation)
                self.reserved = self.reserved + reservation.reserved_cost
        if not decision.allowed:
            detail = {
                **decision.detail,
                "run_id": self.run_id,
                "tenant_id": self.tenant_id,
                "virtual_key_id": self.virtual_key.key_id if self.virtual_key else None,
                "provider_name": provider,
                "agent_id": str(getattr(agent, "id", "") or ""),
                "model_name": str(getattr(agent, "model", "") or ""),
                "context_window": (
                    total_token_ceiling if type(total_token_ceiling) is int else None
                ),
                "estimate_source": estimate_source,
                "channel": channel,
                "prompt_tokens_bound": bounds.prompt_tokens if bounds is not None else None,
                "max_output_tokens_bound": (
                    bounds.max_output_tokens if bounds is not None else None
                ),
            }
            cause: BaseException | None = None
            if decision.reason == "measurement_unavailable":
                detail["unmeasured_calls"] = self._unmeasured_call_evidence(decision)
                with self._lock:
                    cause = self._last_unmeasured_error
            with self._lock:
                self.refusals.append(detail)
            refusal = AffordabilityDecision(
                allowed=False,
                reason=decision.reason,
                scope=decision.scope,
                scope_id=decision.scope_id,
                detail=detail,
            )
            try:
                refusal.raise_if_refused()
            except BudgetExceededError as exc:
                if cause is not None:
                    # Surface the provider failure that made measurement
                    # incomplete instead of only the budget symptom.
                    raise BudgetExceededError(
                        f"{exc} (after unmeasured provider failure: "
                        f"{type(cause).__name__}: {str(cause)[:200]})",
                        detail=exc.detail,
                    ) from cause
                evidence = detail.get("unmeasured_calls") or []
                if evidence:
                    # Another run/process left the unknown outcome: name the
                    # ledger's recorded error class and HTTP status.
                    first = evidence[0]
                    raise BudgetExceededError(
                        f"{exc} (after unmeasured provider failure: "
                        f"{first.get('error_type') or 'unknown error'}"
                        f" status={first.get('provider_status')}"
                        f" reservation={first.get('reservation_id')})",
                        detail=exc.detail,
                    ) from None
                raise
        return Admission(
            price=price,
            reservation=reservation,
            estimate=estimate,
            estimate_source=estimate_source,
            output_cap=output_cap if type(output_cap) is int and output_cap > 0 else None,
        )

    def _unmeasured_call_evidence(self, decision: AffordabilityDecision) -> list[dict[str, Any]]:
        """List the unknown-cost calls behind a ``measurement_unavailable`` refusal.

        In-run failures carry the original error text; calls recorded by other
        runs in a shared scope come from the ledger (error class and status).
        """
        with self._lock:
            evidence = [dict(item) for item in self.unmeasured_failures]
        seen = {item.get("usage_record_id") for item in evidence}
        store = self.guard.store
        if store is None or decision.scope in (None, BudgetScope.RUN):
            return evidence
        limit = next(
            (
                position.limit
                for position in self.positions(self.guard.now())
                if position.limit.scope is decision.scope
                and position.limit.scope_id == decision.scope_id
            ),
            None,
        )
        since = limit.window_start(self.guard.now()) if limit is not None else None
        settled = store.spend_settlements()
        for entry in store.usage_entries(start=since):
            if entry.charged_cost is not None or entry.record.usage_record_id in seen:
                continue
            if entry.reservation_id is not None and entry.reservation_id in settled:
                continue
            if decision.scope is BudgetScope.TENANT and entry.tenant_id != decision.scope_id:
                continue
            if (
                decision.scope is BudgetScope.VIRTUAL_KEY
                and entry.virtual_key_id != decision.scope_id
            ):
                continue
            evidence.append(
                {
                    "usage_record_id": entry.record.usage_record_id,
                    "run_id": entry.run_id,
                    "provider_name": entry.record.provider_name,
                    "model_name": entry.record.model_name,
                    "call_status": entry.call_status,
                    "error_type": entry.error_type,
                    "provider_status": entry.provider_status,
                    "provider_limit_reason": entry.provider_limit_reason,
                    "reservation_id": entry.reservation_id,
                    "created_at": entry.created_at,
                }
            )
        return evidence

    # -- provider limits ----------------------------------------------------
    def observe_failure(self, agent: Any, exc: BaseException) -> ProviderLimitSignal:
        """Classify a provider error; drop the provider for this run on exhaustion."""
        provider = str(getattr(agent, "provider_name", "") or "")
        if not provider:
            return NOT_A_LIMIT
        status, evidence = _error_status_and_evidence(exc)
        if status is None and not evidence:
            return NOT_A_LIMIT
        signal = classify_provider_limit(provider, status, evidence)
        if signal.drops_provider:
            with self._lock:
                first = provider not in self.dropped_providers
                self.dropped_providers.setdefault(provider, signal.reason)
            if first:
                LOGGER.warning(
                    "provider %s dropped for run %s: %s", provider, self.run_id, signal.reason
                )
        return signal

    def is_dropped(self, provider: str) -> bool:
        """Whether ``provider`` has been dropped for the rest of this run."""
        with self._lock:
            return provider in self.dropped_providers

    def filter_candidates(self, agents: list[T]) -> list[T]:
        """Remove agents of dropped providers, unless that would leave none.

        Keeping the full list when everything is dropped lets the transport
        hook raise the typed :class:`ProviderBudgetExhaustedError` instead of
        an opaque "no candidate" failure.
        """
        with self._lock:
            dropped = set(self.dropped_providers)
        if not dropped:
            return agents
        kept = [
            agent for agent in agents if str(getattr(agent, "provider_name", "")) not in dropped
        ]
        return kept or agents

    def _provider_exhausted(
        self,
        agent: Any,
        reason: str,
        *,
        provider_status: int | None,
        transport: str = "chat",
        original: BaseException | None = None,
    ) -> ProviderBudgetExhaustedError:
        """Build the non-retryable error that moves failover past this provider.

        A classified upstream error that was already non-retryable (402, 401)
        keeps its caller-facing code and status; a retryable one (a 429 spend
        limit) is re-coded as :data:`PROVIDER_BUDGET_EXHAUSTED_CODE` / 402 so
        no layer retries it as a rate limit.
        """
        provider = str(getattr(agent, "provider_name", "") or "")
        extra: dict[str, Any] = {
            "provider_name": provider,
            "limit_reason": reason,
            "run_id": self.run_id,
        }
        if provider_status is not None:
            # Kept as evidence only: a 429 status on the typed error would make
            # failover book a rate-limit cooldown and storm-wait on a provider
            # that cannot recover within this run.
            extra["limit_provider_status"] = provider_status
        error_code, client_status = PROVIDER_BUDGET_EXHAUSTED_CODE, 402
        if isinstance(original, ProviderUpstreamError):
            extra = {**original.extra_detail, **extra}
            if not original.retryable:
                error_code, client_status = original.error_code, original.client_status
        return ProviderBudgetExhaustedError(
            agent_id=str(getattr(agent, "id", "")),
            model=str(getattr(agent, "model", "")),
            error_code=error_code,
            message=f"provider {provider} reported an exhausted spend limit ({reason})",
            client_status=client_status,
            provider_status=None,
            retryable=False,
            transport=transport,
            extra_detail=extra,
            limit_evidence=getattr(original, "limit_evidence", None),
        )

    # -- metering -----------------------------------------------------------
    def settle(
        self,
        agent: Any,
        *,
        usage_payload: Any,
        price: Price | None,
        channel: str,
        call_status: str,
        limit_reason: str | None = None,
        known_zero_cost: bool = False,
        reservation: SpendReservation | None = None,
        error: BaseException | None = None,
        bound: Money | None = None,
    ) -> MeteredUsage:
        """Record one provider call and charge its cost to the run.

        ``known_zero_cost`` marks a call the provider refused before any
        response body (a pre-response HTTP 402 spend-limit refusal), which
        providers do not bill; it is charged zero rather than left unknown.

        An unmeasured call (no authoritative cost: a timeout, a connection
        reset after send, a 5xx or a success without usage) counts at its
        admission bound -- the reservation when a hard cap made one, else
        ``bound`` -- and marks the run's measurement incomplete. The ledger
        keeps the charged cost unknown (ADR 0138).
        """
        usage = Usage.from_provider_usage(usage_payload)
        reported = provider_reported_cost(usage_payload)
        provider = str(getattr(agent, "provider_name", "") or "unknown")
        record = self.guard.ledger.record_usage(
            provider=provider,
            model=str(getattr(agent, "model", "")),
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            request_channel=channel,
            workflow_run_id=self.run_id,
            measurement_status="measured" if usage.measured else "unavailable",
        )
        charged: Money | None
        if reported is not None:
            charged, source = reported, "provider_reported"
        elif known_zero_cost and not usage.measured:
            charged, source = Money.zero(self.spent.currency), "zero_cost"
        elif price is not None and price.is_free:
            charged, source = Money.zero(price.currency), "zero_cost"
        elif price is not None and usage.measured:
            charged, source = price.cost_of(usage), "price_book"
        else:
            charged, source = None, "unknown"
        entry = MeteredUsage(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            call_status=call_status,
            record=record,
            charged_cost=charged,
            cost_source=source,
            virtual_key_id=self.virtual_key.key_id if self.virtual_key else None,
            purpose=_CALL_PURPOSE.get().value,
            provider_limit_reason=limit_reason,
            reservation_id=reservation.reservation_id if reservation is not None else None,
            error_type=type(error).__name__ if error is not None else None,
            provider_status=(_error_status_and_evidence(error)[0] if error is not None else None),
        )
        reserved_cost = reservation.reserved_cost if reservation is not None else None
        assumed_bound = reserved_cost if reserved_cost is not None else bound
        with self._lock:
            if reserved_cost is not None:
                self.reserved = self.reserved.minus_floor_zero(reserved_cost)
            self.entries.append(entry)
            if charged is None and error is not None:
                self.unmeasured_failures.append(
                    {
                        "usage_record_id": record.usage_record_id,
                        "run_id": self.run_id,
                        "provider_name": provider,
                        "model_name": str(getattr(agent, "model", "")),
                        "call_status": call_status,
                        "error_type": entry.error_type,
                        "provider_status": entry.provider_status,
                        "provider_limit_reason": limit_reason,
                        "error_message": str(error)[:200],
                        "reservation_id": entry.reservation_id,
                        "created_at": record.created_at,
                    }
                )
                self._last_unmeasured_error = error
            if charged is not None and charged.currency == self.spent.currency:
                self.spent = self.spent + charged
            elif charged is None:
                # The call crossed (or may have crossed) the provider boundary
                # but no authoritative charge came back. Count the proved upper
                # bound -- the reservation under a hard cap, else the admission
                # estimate -- and block later billable calls; never treat the
                # failed/unknown outcome as free.
                if (
                    assumed_bound is not None
                    and assumed_bound.currency == self.spent.currency
                ):
                    self.spent = self.spent + assumed_bound
                self.measurement_complete = False
            if (
                charged is not None
                and assumed_bound is not None
                and charged.currency == assumed_bound.currency
                and charged > assumed_bound
            ):
                # The provider billed more than the admission bound allowed
                # (for example fees outside prompt/completion pricing). Keep
                # the evidence; the actual charge already counts above.
                self.bound_overruns.append(
                    {
                        "usage_record_id": record.usage_record_id,
                        "provider_name": provider,
                        "model_name": str(getattr(agent, "model", "")),
                        "channel": channel,
                        "admission_bound": str(assumed_bound.amount),
                        "charged_cost": str(charged.amount),
                        "cost_source": source,
                    }
                )
                LOGGER.warning(
                    "spend charge exceeded its admission bound: provider=%s model=%s",
                    provider,
                    getattr(agent, "model", ""),
                )
        store = self.guard.store
        if store is not None:
            try:
                if reservation is None:
                    store.append_usage(entry)
                else:
                    with store.budget_transaction():
                        store.append_usage(entry)
                        if charged is not None:
                            store.release_spend_reservation(reservation.reservation_id)
            except Exception as exc:  # noqa: BLE001 - keep the call result; surface the loss
                with self._lock:
                    self.store_failures += 1
                LOGGER.error("spend ledger append failed: %s", type(exc).__name__)
        return entry

    def summary(self) -> dict[str, Any]:
        """JSON run artifact (see :func:`spend_metering.summarize_run`)."""
        now = self.guard.now()
        with self._lock:
            entries = list(self.entries)
            dropped = dict(self.dropped_providers)
            refusals = list(self.refusals)
            store_failures = self.store_failures
            spent = self.spent
            reserved = self.reserved
            complete = self.measurement_complete
            overruns = [dict(item) for item in self.bound_overruns]
            clamps = [dict(item) for item in self.output_cap_clamps]
        cap = self.guard.config.run_max_cost
        budget = {
            "run_max_cost": cap.as_float() if cap is not None else None,
            "run_spent_cost": spent.as_float(),
            "run_reserved_cost": reserved.as_float(),
            "currency": spent.currency,
            "measurement_complete": complete,
            "baseline_min_remaining_ratio": float(self.guard.config.baseline_min_remaining_ratio),
            "limits": [
                {
                    "scope": position.limit.scope.value,
                    "scope_id": position.limit.scope_id,
                    "max_cost": (
                        position.limit.max_cost.as_float()
                        if position.limit.max_cost is not None
                        else None
                    ),
                    "soft_max_cost": (
                        position.limit.soft_max_cost.as_float()
                        if position.limit.soft_max_cost is not None
                        else None
                    ),
                    "spent_cost": position.spent.as_float(),
                    "budget_reset_at": position.limit.reset_at(now),
                }
                for position in self.positions(now)
            ],
            "refusals": refusals,
            "spend_store_failures": store_failures,
            "admission_bound_overruns": overruns,
            "output_cap_clamps": clamps,
            "implicit_scope": self.implicit,
        }
        return summarize_run(
            entries,
            run_id=self.run_id,
            tenant_id=self.tenant_id,
            virtual_key_id=self.virtual_key.key_id if self.virtual_key else None,
            budget=budget,
            dropped_providers=dropped,
        )


@dataclass
class SpendGuard:
    """Owns spend configuration, pricing, durable storage, and run scopes."""

    config: SpendGuardConfig = field(default_factory=SpendGuardConfig)
    price_book: PriceBook | None = None
    ledger: CostLedger | None = None
    store: SpendLedgerStore | None = None
    clock: Callable[[], float] | None = None

    def __post_init__(self) -> None:
        """Wire one price source for both budget estimates and usage records."""
        if self.price_book is None:
            self.price_book = (
                self.ledger.price_book if self.ledger is not None else PriceBook(InMemoryConfigStore())
            )
        if self.ledger is None:
            self.ledger = CostLedger(
                self.price_book, store=_DiscardingLedgerStore(), clock=lambda: self.now()
            )
        self.catalog = PriceBookCatalog(self.price_book)
        self._last_summary: dict[str, Any] | None = None
        self._last_implicit_summary: dict[str, Any] | None = None
        #: Implicit single-call scopes opened so far (ADR 0138 defense in depth).
        self.implicit_scope_count = 0
        self._summary_lock = threading.Lock()

    def now(self) -> int:
        """Current epoch seconds from the injected clock."""
        return int((self.clock or time.time)())

    # -- identity ------------------------------------------------------------
    def resolve_identity(
        self, *, tenant_id: str | None = None, virtual_key: str | None = None
    ) -> tuple[str, VirtualKey | None]:
        """Resolve the trusted tenant: virtual key > explicit trusted tenant > default."""
        key: VirtualKey | None = None
        if virtual_key is not None:
            if self.store is None:
                raise VirtualKeyError("virtual keys require a configured spend ledger store")
            try:
                key_hash = hash_virtual_key(virtual_key)
            except ValueError as exc:
                raise VirtualKeyError("virtual key is malformed") from exc
            key = self.store.virtual_key(key_hash)
            if key is None or key.disabled:
                raise VirtualKeyError("virtual key is unknown or disabled")
            if tenant_id is not None and tenant_id != key.tenant_id:
                raise VirtualKeyError("virtual key belongs to a different tenant")
            return key.tenant_id, key
        if tenant_id is not None:
            return validate_tenant_id(tenant_id), None
        return DEFAULT_TENANT_ID, None

    @contextmanager
    def tenant_context(
        self, *, tenant_id: str | None = None, virtual_key: str | None = None
    ) -> Iterator[tuple[str, VirtualKey | None]]:
        """Attribute runs opened inside this block to a tenant / virtual key.

        Must be entered by the trusted embedding application (for example the
        CLI with an operator-supplied tenant or a KV-held virtual key); never
        from client-declared request attribution.
        """
        identity = self.resolve_identity(tenant_id=tenant_id, virtual_key=virtual_key)
        token = _PENDING_IDENTITY.set(_Identity(*identity))
        try:
            yield identity
        finally:
            _PENDING_IDENTITY.reset(token)

    # -- run scope -----------------------------------------------------------
    @staticmethod
    def active_scope() -> "RunSpendScope | None":
        """The run scope active in the current context, if any."""
        return _ACTIVE_RUN.get()

    def open_run_scope(self, run_id: str | None = None) -> RunSpendScope:
        """Create a scope for a new run using the pending tenant identity."""
        identity = _PENDING_IDENTITY.get() or _Identity(DEFAULT_TENANT_ID, None)
        return RunSpendScope(
            self,
            run_id=run_id or f"spend_run_{uuid.uuid4().hex}",
            tenant_id=identity.tenant_id,
            virtual_key=identity.virtual_key,
        )

    def close_run_scope(self, scope: RunSpendScope) -> None:
        """Remember the finished run's summary for :meth:`last_run_summary`.

        Implicit single-call scopes are recorded separately
        (:meth:`last_implicit_run_summary`) so they never replace the summary
        of the caller's own run.
        """
        summary = scope.summary()
        with self._summary_lock:
            if scope.implicit:
                self._last_implicit_summary = summary
                self.implicit_scope_count += 1
            else:
                self._last_summary = summary

    def open_implicit_scope(self) -> RunSpendScope:
        """A single-call scope for a paid call that reached a hook with no run.

        Defense in depth (ADR 0138): configured caps and metering still apply
        to readiness probes, capability calls, or any future send path that
        was not wrapped in a run scope. The call is logged and summarized.
        """
        scope = self.open_run_scope(f"spend_implicit_{uuid.uuid4().hex}")
        scope.implicit = True
        LOGGER.info("spend guard opened an implicit single-call run scope %s", scope.run_id)
        return scope

    @contextmanager
    def implicit_run_scope(self) -> Iterator[RunSpendScope]:
        """Enter an implicit single-call scope, or join the active run."""
        existing = _ACTIVE_RUN.get()
        if existing is not None:
            yield existing
            return
        scope = self.open_implicit_scope()
        token = _ACTIVE_RUN.set(scope)
        try:
            yield scope
        finally:
            _ACTIVE_RUN.reset(token)
            self.close_run_scope(scope)

    def last_implicit_run_summary(self) -> dict[str, Any] | None:
        """Summary of the most recent implicit single-call scope."""
        with self._summary_lock:
            summary = self._last_implicit_summary
            return None if summary is None else dict(summary)

    @contextmanager
    def run_scope(self, run_id: str | None = None) -> Iterator[RunSpendScope]:
        """Enter a run scope, reusing the active one when runs nest.

        "Per run" means the outermost scope: every top-level entry point,
        implicit single-call scope, and nested ``run_scope`` inside an active
        one joins it (same run id, cap, and ledger). Wrap a whole session --
        for example many ``route_once`` calls or batch rows -- in one
        ``run_scope`` to share one run cap across them.
        """
        existing = _ACTIVE_RUN.get()
        if existing is not None:
            yield existing
            return
        scope = self.open_run_scope(run_id)
        token = _ACTIVE_RUN.set(scope)
        try:
            yield scope
        finally:
            _ACTIVE_RUN.reset(token)
            self.close_run_scope(scope)

    @staticmethod
    @contextmanager
    def call_purpose(purpose: CallPurpose) -> Iterator[None]:
        """Mark provider calls in this block as primary or sampled-baseline work."""
        token = _CALL_PURPOSE.set(purpose)
        try:
            yield
        finally:
            _CALL_PURPOSE.reset(token)

    def last_run_summary(self) -> dict[str, Any] | None:
        """Summary of the most recently finished run scope."""
        with self._summary_lock:
            return None if self._last_summary is None else dict(self._last_summary)

    # -- definitions -----------------------------------------------------------
    def issue_virtual_key(
        self,
        tenant_id: str,
        *,
        max_budget_usd: object | None = None,
        budget_duration: str | None = None,
        soft_budget_usd: object | None = None,
        key_alias: str | None = None,
    ) -> tuple[str, VirtualKey]:
        """Create a virtual key; the plaintext secret is returned exactly once."""
        if self.store is None:
            raise VirtualKeyError("virtual keys require a configured spend ledger store")
        secret = "sk-co-" + secrets.token_urlsafe(32)
        key = VirtualKey(
            key_hash=hash_virtual_key(secret),
            tenant_id=validate_tenant_id(tenant_id),
            max_budget=None if max_budget_usd is None else Money.usd(max_budget_usd),
            budget_duration_seconds=parse_budget_duration(budget_duration),
            soft_budget=None if soft_budget_usd is None else Money.usd(soft_budget_usd),
            created_at=self.now(),
            key_alias=key_alias,
        )
        self.store.put_virtual_key(key)
        return secret, key

    def set_tenant_budget(
        self,
        tenant_id: str,
        *,
        max_budget_usd: object | None = None,
        budget_duration: str | None = None,
        soft_budget_usd: object | None = None,
    ) -> TenantBudget:
        """Create or replace a tenant's shared budget."""
        if self.store is None:
            raise VirtualKeyError("tenant budgets require a configured spend ledger store")
        budget = TenantBudget(
            tenant_id=validate_tenant_id(tenant_id),
            max_budget=None if max_budget_usd is None else Money.usd(max_budget_usd),
            budget_duration_seconds=parse_budget_duration(budget_duration),
            soft_budget=None if soft_budget_usd is None else Money.usd(soft_budget_usd),
            created_at=self.now(),
        )
        self.store.put_tenant_budget(budget)
        return budget


# -- transport hooks (called by ModelClient) ---------------------------------

def _refused_before_billing(signal: ProviderLimitSignal, exc: BaseException) -> bool:
    """Whether a limit error is a pre-response HTTP 402, which providers do not bill.

    OpenRouter documents that a 402 for an exhausted key limit or a zero
    account balance (``limit_source`` ``openrouter_key_limit`` /
    ``openrouter_credits``) is returned before inference and not charged.
    In-stream errors (no HTTP error status) may follow billed output and stay
    unknown.
    """
    if signal.action is ProviderLimitAction.NONE:
        return False
    status, _evidence = _error_status_and_evidence(exc)
    return status == 402


def _call_status(signal: ProviderLimitSignal) -> str:
    return "provider_limit" if signal.action is not ProviderLimitAction.NONE else "error"


def _read_token_bounds(
    reader: Callable[[], AdmissionTokenBounds | None] | None,
) -> AdmissionTokenBounds | None:
    """Evaluate the caller's token-bound hook; any failure means "unknown"."""
    if reader is None:
        return None
    try:
        bounds = reader()
    except Exception:  # noqa: BLE001 - an unavailable bound falls back to the ceiling
        return None
    return bounds if isinstance(bounds, AdmissionTokenBounds) else None


def _read_usage(usage_reader: Callable[[], Any] | None) -> Any:
    if usage_reader is None:
        return None
    try:
        return usage_reader()
    except Exception:  # noqa: BLE001 - usage evidence is optional
        return None


def _drive_in_context(
    inner: Iterator[Any], enter: Callable[[], Callable[[], None]]
) -> Iterator[Any]:
    """Iterate ``inner`` with ``enter()``'s context active only inside each ``next()``.

    ``enter`` sets context variables and returns the function restoring them,
    so values never leak into the consumer between items; ``inner`` is closed
    under the same context.
    """
    try:
        while True:
            restore = enter()
            try:
                item = next(inner)
            except StopIteration as stop:
                return stop.value
            finally:
                restore()
            yield item
    finally:
        restore = enter()
        try:
            close = getattr(inner, "close", None)
            if callable(close):
                close()
        finally:
            restore()


def _enter_egress(
    state: _EgressState, cap: int | None = None
) -> Callable[[], Callable[[], None]]:
    def enter() -> Callable[[], None]:
        egress_token = _EGRESS.set(state)
        cap_token = _ADMITTED_OUTPUT_TOKENS.set(cap)

        def restore() -> None:
            _ADMITTED_OUTPUT_TOKENS.reset(cap_token)
            _EGRESS.reset(egress_token)

        return restore

    return enter


def declare_pre_egress() -> None:
    """Mark the current guarded call's transport as egress-instrumented.

    Real transports call this first; see :class:`_EgressState`. A no-op
    outside a guarded call.
    """
    state = _EGRESS.get()
    if state is not None:
        state.instrumented = True


def mark_provider_egress() -> None:
    """Record that the current guarded call is about to reach the provider.

    Called immediately before the request is handed to the network (the
    retrying sender, the provider opener). Every failure after this point is
    an unknown outcome and counts at the admission bound.
    """
    state = _EGRESS.get()
    if state is not None:
        state.sent = True


def _enter_scope(scope: RunSpendScope) -> Callable[[], Callable[[], None]]:
    def enter() -> Callable[[], None]:
        token = _ACTIVE_RUN.set(scope)
        return lambda: _ACTIVE_RUN.reset(token)

    return enter


def enforce_admitted_output_cap(payload: dict[str, Any], *, field: str = "max_tokens") -> dict[str, Any]:
    """Keep the sent output cap within what the call's admission bound assumed.

    Called by transports after every payload rewrite (effort profile, shared
    context budget) and immediately before egress. Outside a narrow-bound
    admission this is a no-op. A missing cap is set to the admitted value; a
    larger cap is lowered to it and the clamp is recorded on the run scope.
    """
    cap = _ADMITTED_OUTPUT_TOKENS.get()
    if cap is None or not isinstance(payload, dict):
        return payload
    requested = payload.get(field)
    if type(requested) is int and 0 < requested <= cap:
        return payload
    payload[field] = cap
    if requested is not None:
        scope = _ACTIVE_RUN.get()
        if scope is not None:
            with scope._lock:
                scope.output_cap_clamps.append(
                    {"field": field, "requested": requested, "admitted": cap}
                )
        LOGGER.warning(
            "spend guard lowered %s from %r to the admitted %d output tokens",
            field,
            requested,
            cap,
        )
    return payload


def passthrough_token_bounds(
    agent: Any, payload: Any, token_counter: Any = None
) -> AdmissionTokenBounds | None:
    """Derive admission token bounds from a passthrough request body.

    The prompt count is exact only for a chat ``messages`` body whose other
    keys are prompt-neutral (:data:`_PROMPT_NEUTRAL_KEYS`) and whose content
    the provenance-bound counter can frame; the output cap is the body's
    ``max_tokens`` / ``max_completion_tokens`` / ``max_output_tokens``
    (largest wins) times ``n``. Embedding ``input`` lists count one call per
    input for the ceiling fallback. Anything unknown stays ``None`` so
    admission falls back to the context-window ceiling or refuses.
    """
    if not isinstance(payload, dict):
        return None
    calls = 1
    n = payload.get("n")
    if type(n) is int and n > 1:
        calls = n
    inputs = payload.get("input")
    if isinstance(inputs, list) and inputs and "messages" not in payload:
        calls = max(calls, len(inputs))
    caps = [
        payload.get(key)
        for key in ("max_tokens", "max_completion_tokens", "max_output_tokens")
        if type(payload.get(key)) is int and payload.get(key) > 0
    ]
    max_output = max(caps) * calls if caps else None
    prompt_tokens: int | None = None
    messages = payload.get("messages")
    if (
        isinstance(messages, list)
        and token_counter is not None
        and set(payload).issubset(_PROMPT_NEUTRAL_KEYS)
    ):
        from .token_counting import describe_message_count

        try:
            prompt_tokens = describe_message_count(
                token_counter,
                messages,
                str(payload.get("model") or getattr(agent, "model", "")),
                tools=payload.get("tools"),
            ).token_count
        except Exception:  # noqa: BLE001 - an unframeable body falls back to the ceiling
            prompt_tokens = None
        if type(prompt_tokens) is not int or prompt_tokens < 0:
            prompt_tokens = None
    return AdmissionTokenBounds(
        prompt_tokens=prompt_tokens, max_output_tokens=max_output, calls=calls
    )


def _passthrough_usage(result: Any) -> Any:
    """A passthrough response's ``usage``, completing embeddings-style usage.

    Embedding responses report ``prompt_tokens`` and ``total_tokens`` only;
    when they are equal, the call produced no output tokens, so completion is
    measured as zero rather than making the whole call unmeasured.
    """
    usage = result.get("usage") if isinstance(result, dict) else None
    if (
        isinstance(usage, dict)
        and "completion_tokens" not in usage
        and "output_tokens" not in usage
    ):
        prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
        total = usage.get("total_tokens")
        if type(prompt) is int and type(total) is int and total == prompt:
            return {**usage, "completion_tokens": 0}
    return usage


@contextmanager
def _call_scope(guard: SpendGuard | None) -> Iterator[RunSpendScope | None]:
    """The active run, else an implicit single-call scope from ``guard``, else none."""
    scope = _ACTIVE_RUN.get()
    if scope is not None or guard is None:
        yield scope
        return
    with guard.implicit_run_scope() as implicit:
        yield implicit


def _settle_failure(
    scope: RunSpendScope,
    agent: Any,
    exc: BaseException,
    admission: Admission,
    *,
    usage_payload: Any,
    channel: str,
    egress: _EgressState | None = None,
) -> ProviderLimitSignal:
    not_sent = egress is not None and egress.provably_not_sent
    signal = NOT_A_LIMIT if not_sent else scope.observe_failure(agent, exc)
    scope.settle(
        agent,
        usage_payload=usage_payload,
        price=admission.price,
        channel=channel,
        call_status=_call_status(signal),
        limit_reason=signal.reason or None,
        known_zero_cost=not_sent or _refused_before_billing(signal, exc),
        reservation=admission.reservation,
        error=exc,
        bound=admission.estimate,
    )
    return signal


def guarded_provider_call(
    agent: Any,
    messages: Any,
    call: Callable[[], T],
    *,
    usage_reader: Callable[[], Any] | None,
    channel: str = "sync",
    token_bounds: Callable[[], AdmissionTokenBounds | None] | None = None,
    guard: SpendGuard | None = None,
) -> T:
    """Admit, execute, meter, and limit-classify one chat call in the active run.

    Without an active run the call runs in an implicit single-call scope of
    ``guard`` (configured caps and metering still apply); only a client with
    no guard at all passes through unmetered.
    """
    del messages  # admission prices the token bounds, not the raw messages
    with _call_scope(guard) as scope:
        if scope is None:
            return call()
        admission = scope.admit_call(
            agent, token_bounds=_read_token_bounds(token_bounds), channel=channel
        )
        egress = _EgressState()
        restore = _enter_egress(egress, admission.output_cap)()
        try:
            result = call()
        except Exception as exc:
            signal = _settle_failure(
                scope, agent, exc, admission,
                usage_payload=_read_usage(usage_reader), channel=channel, egress=egress,
            )
            if signal.drops_provider:
                status, _evidence = _error_status_and_evidence(exc)
                raise scope._provider_exhausted(
                    agent, signal.reason, provider_status=status, transport="chat", original=exc
                ) from None
            raise
        finally:
            restore()
        scope.settle(
            agent,
            usage_payload=_read_usage(usage_reader),
            price=admission.price,
            channel=channel,
            call_status="ok",
            reservation=admission.reservation,
            bound=admission.estimate,
        )
        return result


def guarded_provider_stream(
    agent: Any,
    messages: Any,
    open_stream: Callable[[], Iterator[T]],
    *,
    usage_reader: Callable[[], Any] | None,
    token_bounds: Callable[[], AdmissionTokenBounds | None] | None = None,
    guard: SpendGuard | None = None,
) -> Iterator[T]:
    """Streaming counterpart of :func:`guarded_provider_call`."""
    del messages
    scope = _ACTIVE_RUN.get()
    if scope is None:
        if guard is None:
            yield from open_stream()
            return
        implicit = guard.open_implicit_scope()
        try:
            yield from _drive_in_context(
                _guarded_stream_body(implicit, agent, open_stream, usage_reader, token_bounds),
                _enter_scope(implicit),
            )
        finally:
            guard.close_run_scope(implicit)
        return
    yield from _guarded_stream_body(scope, agent, open_stream, usage_reader, token_bounds)


def _guarded_stream_body(
    scope: RunSpendScope,
    agent: Any,
    open_stream: Callable[[], Iterator[Any]],
    usage_reader: Callable[[], Any] | None,
    token_bounds: Callable[[], AdmissionTokenBounds | None] | None,
) -> Iterator[Any]:
    admission = scope.admit_call(
        agent, token_bounds=_read_token_bounds(token_bounds), channel="stream"
    )
    settled = False
    egress = _EgressState()
    try:
        yield from _drive_in_context(open_stream(), _enter_egress(egress, admission.output_cap))
    except Exception as exc:
        settled = True
        signal = _settle_failure(
            scope, agent, exc, admission,
            usage_payload=_read_usage(usage_reader), channel="stream", egress=egress,
        )
        if signal.drops_provider:
            status, _evidence = _error_status_and_evidence(exc)
            raise scope._provider_exhausted(
                agent, signal.reason, provider_status=status, transport="stream", original=exc
            ) from None
        raise
    finally:
        if not settled:
            scope.settle(
                agent,
                usage_payload=_read_usage(usage_reader),
                price=admission.price,
                channel="stream",
                call_status="ok",
                reservation=admission.reservation,
                bound=admission.estimate,
            )


def metered_passthrough_call(
    agent: Any,
    call: Callable[[], T],
    *,
    channel: str = "passthrough",
    payload: Any = None,
    token_counter: Any = None,
    token_bounds: AdmissionTokenBounds | None = None,
    usage_from_result: Callable[[Any], Any] | None = None,
    guard: SpendGuard | None = None,
) -> T:
    """Admit, execute, and meter one passthrough / binary / embedding / batch call.

    Admission is the same as for chat (reservation, tightest limit, baseline
    headroom rule): the bound comes from ``token_bounds`` or is derived from
    the request ``payload`` (:func:`passthrough_token_bounds`), else the
    context-window ceiling, else the call is refused before it is sent.
    Provider errors are metered and classified but never rewritten.
    """
    with _call_scope(guard) as scope:
        if scope is None:
            return call()
        bounds = (
            token_bounds
            if isinstance(token_bounds, AdmissionTokenBounds)
            else passthrough_token_bounds(agent, payload, token_counter)
        )
        admission = scope.admit_call(agent, token_bounds=bounds, channel=channel)
        egress = _EgressState()
        restore = _enter_egress(egress, admission.output_cap)()
        try:
            result = call()
        except Exception as exc:
            _settle_failure(
                scope, agent, exc, admission, usage_payload=None, channel=channel, egress=egress
            )
            raise
        finally:
            restore()
        if usage_from_result is not None:
            try:
                usage_payload = usage_from_result(result)
            except Exception:  # noqa: BLE001 - usage evidence is optional
                usage_payload = None
        else:
            usage_payload = _passthrough_usage(result)
        scope.settle(
            agent,
            usage_payload=usage_payload,
            price=admission.price,
            channel=channel,
            call_status="ok",
            reservation=admission.reservation,
            bound=admission.estimate,
        )
        return result


def raise_if_stream_limit_event(agent: Any, chunk: Any) -> None:
    """Raise when a streamed HTTP 200 chunk carries a provider limit-exhaustion error.

    Only limit errors (drop or transient) are raised; any other in-stream error
    object keeps the transport's existing handling.
    """
    if not isinstance(chunk, dict) or not isinstance(chunk.get("error"), dict):
        return
    evidence = limit_evidence_from_payload(chunk)
    provider = str(getattr(agent, "provider_name", "") or "")
    signal = classify_provider_limit(provider, None, evidence)
    if signal.action is ProviderLimitAction.NONE:
        return
    raise ProviderUpstreamError(
        agent_id=str(getattr(agent, "id", "")),
        model=str(getattr(agent, "model", "")),
        error_code=(
            PROVIDER_BUDGET_EXHAUSTED_CODE
            if signal.drops_provider
            else "payment_required"
        ),
        message=f"provider {provider} reported a spend limit mid-stream ({signal.reason})",
        client_status=402,
        provider_status=None,
        retryable=False,
        transport="stream",
        limit_evidence=evidence,
    )


def with_run_scope(method: Callable[..., T]) -> Callable[..., T]:
    """Decorate a ``TaskOrchestrator`` entry point so it runs inside a spend run scope.

    Generator methods (``stream_route``) re-enter the scope around every
    ``next()`` so the context variable never leaks into the consumer.
    """
    import functools
    import inspect

    if inspect.isgeneratorfunction(method):

        @functools.wraps(method)
        def generator_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            guard = getattr(self, "spend_guard", None)
            if guard is None or _ACTIVE_RUN.get() is not None:
                return (yield from method(self, *args, **kwargs))
            scope = guard.open_run_scope(kwargs.get("workflow_run_id"))
            try:
                return (
                    yield from _drive_in_context(
                        method(self, *args, **kwargs), _enter_scope(scope)
                    )
                )
            finally:
                guard.close_run_scope(scope)

        return generator_wrapper  # type: ignore[return-value]

    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> T:
        guard = getattr(self, "spend_guard", None)
        if guard is None:
            return method(self, *args, **kwargs)
        with guard.run_scope(kwargs.get("workflow_run_id")):
            return method(self, *args, **kwargs)

    return wrapper


__all__ = [
    "PROVIDER_BUDGET_EXHAUSTED_CODE",
    "SPEND_GUARD_CONFIG_CATEGORY",
    "Admission",
    "PriceBookCatalog",
    "ProviderBudgetExhaustedError",
    "RunSpendScope",
    "SpendGuard",
    "SpendGuardConfig",
    "VirtualKeyError",
    "declare_pre_egress",
    "enforce_admitted_output_cap",
    "guarded_provider_call",
    "guarded_provider_stream",
    "mark_provider_egress",
    "metered_passthrough_call",
    "passthrough_token_bounds",
    "raise_if_stream_limit_event",
    "with_run_scope",
]
