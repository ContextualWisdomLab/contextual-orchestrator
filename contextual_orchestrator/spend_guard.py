"""Spend guard: per-run cap, virtual-key and tenant budgets, provider drop.

This is the application service around the pure rules in
:mod:`contextual_orchestrator.domain`. One :class:`SpendGuard` belongs to a
``TaskOrchestrator``; every top-level run (``complete``, ``run``,
``route_once``, ``conduct``, ``stream_route``, ``proxy_completion``,
``compare_to_baseline``) opens a :class:`RunSpendScope` held in a
:class:`contextvars.ContextVar`, so concurrent server requests never share a
run budget and worker threads started with ``copy_context`` see their run.

``ModelClient`` calls three thin hooks at its transport boundary:

* :func:`guarded_provider_call` / :func:`guarded_provider_stream` for chat and
  streamed chat: refuse a call to a provider already dropped in this run,
  refuse a call no active budget can afford (tightest limit wins), then meter
  the call and classify a limit-exhaustion error (drop that provider).
* :func:`metered_passthrough_call` for passthrough/binary calls: meter and
  classify only (admission for passthrough happens once per request).
* :func:`raise_if_stream_limit_event` for an error object arriving inside a
  streamed HTTP 200 response.

Outside a run scope every hook is a no-op pass-through. See ADR 0138.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import logging
import secrets
import threading
import time
import urllib.error
import uuid
from typing import Any, Callable, Iterator, TypeVar

from .cost_ledger import CostLedger, PriceBook, UsageRecord
from .domain.budget import (
    AffordabilityDecision,
    BudgetScope,
    CallPurpose,
    SpendLimit,
    SpendPosition,
    decide_affordability,
    parse_budget_duration,
)
from .domain.money import Money, Price, Usage, provider_reported_cost
from .domain.pricing import effective_price, estimate_call_cost
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
from .spend_metering import MeteredUsage, SpendLedgerStore, spent_in_scope, summarize_run

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
    Paid sampled baselines fail closed under an active hard cap unless a
    future versioned allocation authority is supplied; no numeric threshold
    is inferred here.
    """

    run_max_cost: Money | None = None

    @classmethod
    def from_values(
        cls,
        *,
        run_max_cost_usd: object | None = None,
    ) -> "SpendGuardConfig":
        """Build a config from plain numbers (``None`` keeps the default)."""
        return cls(
            run_max_cost=None if run_max_cost_usd is None else Money.usd(run_max_cost_usd),
        )

    @classmethod
    def from_config_store(cls, store: Any) -> "SpendGuardConfig":
        """Read ``run_max_cost_usd`` from the KV store."""
        return cls.from_values(
            run_max_cost_usd=store.get(SPEND_GUARD_CONFIG_CATEGORY, "run_max_cost_usd", None),
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
            spent, _unpriced = spent_in_scope(
                store.usage_entries() if store is not None else self.entries,
                scope=limit.scope,
                scope_id=limit.scope_id,
                since=limit.window_start(now),
                currency=currency,
            )
            with self._lock:
                spent = spent + self.reserved
            positions.append(SpendPosition(limit, spent, True))
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
        )
        for crossed in decision.soft_budget_crossed:
            if crossed not in self._soft_alerts:
                self._soft_alerts.add(crossed)
                LOGGER.warning("spend soft budget crossed: %s", crossed)
        return decision

    def baseline_admissible(self) -> bool:
        """Whether a sampled baseline comparison may still spend in this run."""
        return self.decide(Money.zero(self.spent.currency), CallPurpose.BASELINE).allowed

    def raise_if_exhausted(self) -> None:
        """Raise ``BudgetExceededError`` when any active budget is already exhausted."""
        self.decide(Money.zero(self.spent.currency), CallPurpose.PRIMARY).raise_if_refused()

    def admit(self, agent: Any, messages: Any) -> tuple[Price | None, Money | None]:
        """Atomically reserve an affordable call's cost ceiling and return it with price."""
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
        if price is None:
            estimate = None
            unknown_estimate_reason = "price_unknown"
        elif price.is_free:
            estimate = Money.zero(price.currency)
            unknown_estimate_reason = "price_unknown"
        elif type(total_token_ceiling) is int and total_token_ceiling > 0:
            estimate = estimate_call_cost(price, total_token_ceiling)
            unknown_estimate_reason = "price_unknown"
        else:
            estimate = None
            unknown_estimate_reason = "cost_upper_bound_unavailable"
        purpose = _CALL_PURPOSE.get()
        with self._lock:
            has_hard_cap = any(
                position.limit.max_cost is not None
                for position in self.positions(self.guard.now())
            )
            decision = self.decide(
                estimate,
                purpose,
                unknown_estimate_reason=unknown_estimate_reason,
            )
            reservation = estimate if decision.allowed and has_hard_cap else None
            if reservation is not None:
                self.reserved = self.reserved + reservation
        if not decision.allowed:
            detail = {
                **decision.detail,
                "run_id": self.run_id,
                "tenant_id": self.tenant_id,
                "virtual_key_id": self.virtual_key.key_id if self.virtual_key else None,
                "provider_name": provider,
            }
            with self._lock:
                self.refusals.append(detail)
            AffordabilityDecision(
                allowed=False,
                reason=decision.reason,
                scope=decision.scope,
                scope_id=decision.scope_id,
                detail=detail,
            ).raise_if_refused()
        return price, reservation

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
        reserved_cost: Money | None = None,
    ) -> MeteredUsage:
        """Record one provider call and charge its cost to the run.

        ``known_zero_cost`` marks a call the provider refused before any
        response body (a pre-response HTTP 402 spend-limit refusal), which
        providers do not bill; it is charged zero rather than left unknown.
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
        )
        with self._lock:
            if reserved_cost is not None:
                self.reserved = self.reserved.minus_floor_zero(reserved_cost)
            self.entries.append(entry)
            if charged is not None and charged.currency == self.spent.currency:
                self.spent = self.spent + charged
            elif charged is None and reserved_cost is not None:
                # The call crossed the provider boundary, but no authoritative
                # charge came back. Consume the already-proved upper bound for
                # admission and block later billable calls; never release the
                # reservation as if the failed/unknown outcome were free.
                self.spent = self.spent + reserved_cost
                self.measurement_complete = False
            elif charged is None and call_status == "ok":
                # Without a hard cap there is no reservation to consume, but
                # retain the incomplete-measurement evidence in the receipt.
                self.measurement_complete = False
        store = self.guard.store
        if store is not None:
            try:
                store.append_usage(entry)
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
        cap = self.guard.config.run_max_cost
        budget = {
            "run_max_cost": cap.as_float() if cap is not None else None,
            "run_spent_cost": spent.as_float(),
            "run_reserved_cost": reserved.as_float(),
            "currency": spent.currency,
            "measurement_complete": complete,
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
        """Remember the finished run's summary for :meth:`last_run_summary`."""
        summary = scope.summary()
        with self._summary_lock:
            self._last_summary = summary

    @contextmanager
    def run_scope(self, run_id: str | None = None) -> Iterator[RunSpendScope]:
        """Enter a run scope, reusing the active one when runs nest."""
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


def _read_usage(usage_reader: Callable[[], Any] | None) -> Any:
    if usage_reader is None:
        return None
    try:
        return usage_reader()
    except Exception:  # noqa: BLE001 - usage evidence is optional
        return None


def guarded_provider_call(
    agent: Any,
    messages: Any,
    call: Callable[[], T],
    *,
    usage_reader: Callable[[], Any] | None,
    channel: str = "sync",
) -> T:
    """Admit, execute, meter, and limit-classify one chat call in the active run."""
    scope = _ACTIVE_RUN.get()
    if scope is None:
        return call()
    price, reserved_cost = scope.admit(agent, messages)
    try:
        result = call()
    except Exception as exc:
        signal = scope.observe_failure(agent, exc)
        scope.settle(
            agent,
            usage_payload=_read_usage(usage_reader),
            price=price,
            channel=channel,
            call_status=_call_status(signal),
            limit_reason=signal.reason or None,
            known_zero_cost=_refused_before_billing(signal, exc),
            reserved_cost=reserved_cost,
        )
        if signal.drops_provider:
            status, _evidence = _error_status_and_evidence(exc)
            raise scope._provider_exhausted(
                agent, signal.reason, provider_status=status, transport="chat", original=exc
            ) from None
        raise
    scope.settle(
        agent,
        usage_payload=_read_usage(usage_reader),
        price=price,
        channel=channel,
        call_status="ok",
        reserved_cost=reserved_cost,
    )
    return result


def guarded_provider_stream(
    agent: Any,
    messages: Any,
    open_stream: Callable[[], Iterator[T]],
    *,
    usage_reader: Callable[[], Any] | None,
) -> Iterator[T]:
    """Streaming counterpart of :func:`guarded_provider_call`."""
    scope = _ACTIVE_RUN.get()
    if scope is None:
        yield from open_stream()
        return
    price, reserved_cost = scope.admit(agent, messages)
    settled = False
    try:
        yield from open_stream()
    except Exception as exc:
        signal = scope.observe_failure(agent, exc)
        settled = True
        scope.settle(
            agent,
            usage_payload=_read_usage(usage_reader),
            price=price,
            channel="stream",
            call_status=_call_status(signal),
            limit_reason=signal.reason or None,
            known_zero_cost=_refused_before_billing(signal, exc),
            reserved_cost=reserved_cost,
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
                price=price,
                channel="stream",
                call_status="ok",
                reserved_cost=reserved_cost,
            )


def metered_passthrough_call(
    agent: Any,
    call: Callable[[], T],
    *,
    channel: str = "passthrough",
) -> T:
    """Meter and limit-classify one passthrough call; never refuses or rewrites errors."""
    scope = _ACTIVE_RUN.get()
    if scope is None:
        return call()
    price = effective_price(
        scope.guard.catalog,
        provider=str(getattr(agent, "provider_name", "") or ""),
        model=str(getattr(agent, "model", "")),
        base_url=str(getattr(agent, "base_url", "")),
        tags=tuple(getattr(agent, "tags", ()) or ()),
    )
    try:
        result = call()
    except Exception as exc:
        signal = scope.observe_failure(agent, exc)
        scope.settle(
            agent,
            usage_payload=None,
            price=price,
            channel=channel,
            call_status=_call_status(signal),
            limit_reason=signal.reason or None,
            known_zero_cost=_refused_before_billing(signal, exc),
        )
        raise
    usage_payload = result.get("usage") if isinstance(result, dict) else None
    scope.settle(agent, usage_payload=usage_payload, price=price, channel=channel, call_status="ok")
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
            inner = method(self, *args, **kwargs)
            try:
                while True:
                    token = _ACTIVE_RUN.set(scope)
                    try:
                        item = next(inner)
                    except StopIteration as stop:
                        return stop.value
                    finally:
                        _ACTIVE_RUN.reset(token)
                    yield item
            finally:
                token = _ACTIVE_RUN.set(scope)
                try:
                    inner.close()
                finally:
                    _ACTIVE_RUN.reset(token)
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
    "PriceBookCatalog",
    "ProviderBudgetExhaustedError",
    "RunSpendScope",
    "SpendGuard",
    "SpendGuardConfig",
    "VirtualKeyError",
    "guarded_provider_call",
    "guarded_provider_stream",
    "metered_passthrough_call",
    "raise_if_stream_limit_event",
    "with_run_scope",
]
