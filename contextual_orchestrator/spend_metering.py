"""Per-tenant usage metering and budget-definition storage (port + adapters).

Every provider call made inside a guarded run produces one
:class:`MeteredUsage`: the ``cost_ledger.UsageRecord`` built by
``CostLedger.record_usage`` (tokens, PriceBook cost, ``price_known``,
measurement status, run id) wrapped with the trusted tenant id, the virtual
key id, the call status, and the cost actually charged to budgets.

GitHub Actions runners are ephemeral, so storage sits behind the
:class:`SpendLedgerStore` port with two adapters:

* :class:`InMemorySpendLedgerStore` - process-local (tests, long-lived server).
* :class:`JsonlSpendLedgerStore` - durable append-only JSON Lines file that
  holds usage events *and* virtual-key / tenant-budget definitions, so one file
  (for example restored from an Actions cache or artifact) carries both the
  budgets and the spend accumulated against them across runs.

The run summary (:func:`summarize_run`) is written as a JSON artifact so
callers can aggregate across runs.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, ContextManager, Iterable, Iterator, Mapping, Protocol

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX production/runtime contract
    fcntl = None  # type: ignore[assignment]

from .cost_ledger import AttributionDimensions, UsageRecord
from .domain.budget import BudgetScope
from .domain.money import Money
from .domain.tenancy import TenantBudget, VirtualKey

RUN_SUMMARY_SCHEMA = "contextual_orchestrator.run_usage_summary.v1"
CALL_STATUSES = ("ok", "error", "provider_limit")
COST_SOURCES = ("provider_reported", "price_book", "zero_cost", "unknown")
GROUP_BY_FIELDS = (
    "tenant_id",
    "virtual_key_id",
    "provider_name",
    "model_name",
    "run_id",
    "call_status",
)


def _usage_record_from_row(row: dict[str, Any]) -> UsageRecord:
    """Rebuild a ``UsageRecord`` from its ``as_dict`` row."""
    return UsageRecord(
        usage_record_id=row["usage_record_id"],
        created_at=int(row["created_at"]),
        workflow_run_id=row.get("workflow_run_id"),
        request_channel=row.get("request_channel", "sync"),
        route_mode=row.get("route_mode"),
        provider_name=row["provider_name"],
        model_name=row["model_name"],
        prompt_tokens=int(row["prompt_tokens"]),
        completion_tokens=int(row["completion_tokens"]),
        total_tokens=int(row["total_tokens"]),
        cost_amount=float(row["cost_amount"]),
        currency_code=row["currency_code"],
        measurement_status=row.get("measurement_status", "measured"),
        price_known=bool(row.get("price_known", True)),
        attribution=AttributionDimensions(
            account=row.get("account_name", "unattributed"),
            service=row.get("service_name", "unattributed"),
            upstream_api=row.get("upstream_api", row["provider_name"]),
            model_name=row["model_name"],
            team=row.get("team_name", "unattributed"),
            group=row.get("group_name", "unattributed"),
            company=row.get("company_name", "unattributed"),
        ),
    )


@dataclass(frozen=True)
class MeteredUsage:
    """One provider call attributed to a tenant (and optionally a virtual key)."""

    tenant_id: str
    run_id: str
    call_status: str
    record: UsageRecord
    charged_cost: Money | None
    cost_source: str
    virtual_key_id: str | None = None
    purpose: str = "primary"
    provider_limit_reason: str | None = None
    #: Hard-cap reservation this call consumed; links an unknown outcome to an
    #: operator settlement (ADR 0138).
    reservation_id: str | None = None
    #: Original provider failure class and HTTP status for a failed call, so a
    #: later ``measurement_unavailable`` refusal can name its cause.
    error_type: str | None = None
    provider_status: int | None = None

    def __post_init__(self) -> None:
        """Keep status and cost-source vocabularies closed."""
        if self.call_status not in CALL_STATUSES:
            raise ValueError(f"call_status must be one of {CALL_STATUSES}")
        if self.cost_source not in COST_SOURCES:
            raise ValueError(f"cost_source must be one of {COST_SOURCES}")
        if (self.charged_cost is None) != (self.cost_source == "unknown"):
            raise ValueError("charged_cost is None exactly when cost_source is 'unknown'")

    @property
    def created_at(self) -> int:
        """Epoch seconds of the underlying usage record."""
        return self.record.created_at

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe row: the ledger record plus tenant metering fields."""
        return {
            "tenant_id": self.tenant_id,
            "virtual_key_id": self.virtual_key_id,
            "run_id": self.run_id,
            "call_status": self.call_status,
            "purpose": self.purpose,
            "provider_limit_reason": self.provider_limit_reason,
            "charged_cost_usd": (
                self.charged_cost.as_float() if self.charged_cost is not None else None
            ),
            "charged_cost": (
                {"amount": str(self.charged_cost.amount), "currency": self.charged_cost.currency}
                if self.charged_cost is not None
                else None
            ),
            "cost_source": self.cost_source,
            "price_unknown": self.cost_source == "unknown",
            "reservation_id": self.reservation_id,
            "error_type": self.error_type,
            "provider_status": self.provider_status,
            "record": self.record.as_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MeteredUsage":
        """Rebuild an entry from :meth:`as_dict` output."""
        charged = data.get("charged_cost")
        return cls(
            tenant_id=data["tenant_id"],
            run_id=data["run_id"],
            call_status=data["call_status"],
            record=_usage_record_from_row(data["record"]),
            charged_cost=(
                Money(charged["amount"], charged.get("currency", "USD"))
                if isinstance(charged, dict)
                else None
            ),
            cost_source=data["cost_source"],
            virtual_key_id=data.get("virtual_key_id"),
            purpose=data.get("purpose", "primary"),
            provider_limit_reason=data.get("provider_limit_reason"),
            reservation_id=data.get("reservation_id"),
            error_type=data.get("error_type"),
            provider_status=(
                data["provider_status"] if type(data.get("provider_status")) is int else None
            ),
        )


@dataclass(frozen=True)
class SpendReservation:
    """One durable pre-call cost upper bound shared across run scopes."""

    reservation_id: str
    tenant_id: str
    run_id: str
    reserved_cost: Money
    created_at: int
    virtual_key_id: str | None = None

    def __post_init__(self) -> None:
        """Reject identifiers or amounts that cannot authorize admission."""
        if not self.reservation_id or not self.tenant_id or not self.run_id:
            raise ValueError("reservation_id, tenant_id, and run_id are required")
        if self.reserved_cost.amount <= 0:
            raise ValueError("reserved_cost must be positive")
        if type(self.created_at) is not int or self.created_at < 0:
            raise ValueError("created_at must be a non-negative integer")

    def as_dict(self) -> dict[str, Any]:
        """Return the append-only ledger representation."""
        return {
            "reservation_id": self.reservation_id,
            "tenant_id": self.tenant_id,
            "virtual_key_id": self.virtual_key_id,
            "run_id": self.run_id,
            "reserved_cost": {
                "amount": str(self.reserved_cost.amount),
                "currency": self.reserved_cost.currency,
            },
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpendReservation":
        """Rebuild a reservation from an append-only ledger event."""
        cost = data["reserved_cost"]
        return cls(
            reservation_id=data["reservation_id"],
            tenant_id=data["tenant_id"],
            virtual_key_id=data.get("virtual_key_id"),
            run_id=data["run_id"],
            reserved_cost=Money(cost["amount"], cost.get("currency", "USD")),
            created_at=int(data["created_at"]),
        )


@dataclass(frozen=True)
class SpendSettlement:
    """An explicit operator settlement of one active reservation (ADR 0138).

    An unknown provider outcome leaves its reservation active and its usage
    entry unpriced, which keeps every hard budget that covers it fail closed.
    An operator who has authoritative evidence (for example the provider's
    billing console) closes that state with an append-only settlement: the
    ``settled_cost`` (zero is allowed but must be stated explicitly) replaces
    both the reservation and the linked unknown usage cost in every budget
    sum, attributed to the reservation's tenant, key, run and time. ``reason``
    and ``settled_by`` are required so the ledger explains every release.
    """

    reservation_id: str
    tenant_id: str
    run_id: str
    reserved_cost: Money
    reserved_at: int
    settled_cost: Money
    settled_at: int
    settled_by: str
    reason: str
    virtual_key_id: str | None = None

    def __post_init__(self) -> None:
        """Require an audit trail and a non-negative same-currency amount."""
        if not self.reservation_id or not self.tenant_id or not self.run_id:
            raise ValueError("reservation_id, tenant_id, and run_id are required")
        if not str(self.reason).strip():
            raise ValueError("a settlement reason is required")
        if not str(self.settled_by).strip():
            raise ValueError("settled_by (the operator) is required")
        if self.settled_cost.currency != self.reserved_cost.currency:
            raise ValueError("settled_cost must use the reservation currency")
        for name in ("reserved_at", "settled_at"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    @classmethod
    def for_reservation(
        cls,
        reservation: SpendReservation,
        *,
        settled_cost: Money,
        settled_at: int,
        settled_by: str,
        reason: str,
    ) -> SpendSettlement:
        """Build a settlement that inherits the reservation's attribution."""
        return cls(
            reservation_id=reservation.reservation_id,
            tenant_id=reservation.tenant_id,
            virtual_key_id=reservation.virtual_key_id,
            run_id=reservation.run_id,
            reserved_cost=reservation.reserved_cost,
            reserved_at=reservation.created_at,
            settled_cost=settled_cost,
            settled_at=settled_at,
            settled_by=settled_by,
            reason=reason,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the append-only ledger representation."""
        return {
            "reservation_id": self.reservation_id,
            "tenant_id": self.tenant_id,
            "virtual_key_id": self.virtual_key_id,
            "run_id": self.run_id,
            "reserved_cost": {
                "amount": str(self.reserved_cost.amount),
                "currency": self.reserved_cost.currency,
            },
            "reserved_at": self.reserved_at,
            "settled_cost": {
                "amount": str(self.settled_cost.amount),
                "currency": self.settled_cost.currency,
            },
            "settled_at": self.settled_at,
            "settled_by": self.settled_by,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpendSettlement:
        """Rebuild a settlement from an append-only ledger event."""
        reserved = data["reserved_cost"]
        settled = data["settled_cost"]
        return cls(
            reservation_id=data["reservation_id"],
            tenant_id=data["tenant_id"],
            virtual_key_id=data.get("virtual_key_id"),
            run_id=data["run_id"],
            reserved_cost=Money(reserved["amount"], reserved.get("currency", "USD")),
            reserved_at=int(data["reserved_at"]),
            settled_cost=Money(settled["amount"], settled.get("currency", "USD")),
            settled_at=int(data["settled_at"]),
            settled_by=data["settled_by"],
            reason=data["reason"],
        )


class SpendLedgerStore(Protocol):
    """Storage port for metered usage and budget definitions."""

    def append_usage(self, entry: MeteredUsage) -> bool:
        """Persist one usage entry; ``False`` when its record id already exists."""
        ...

    def usage_entries(
        self, start: int | None = None, end: int | None = None
    ) -> list[MeteredUsage]:
        """Entries created in ``[start, end)`` (``None`` is unbounded)."""
        ...

    def put_virtual_key(self, key: VirtualKey) -> None:
        """Create or replace a virtual key definition (digest only)."""
        ...

    def virtual_key(self, key_hash: str) -> VirtualKey | None:
        """Look up a key definition by digest."""
        ...

    def virtual_keys(self) -> list[VirtualKey]:
        """All stored key definitions."""
        ...

    def put_tenant_budget(self, budget: TenantBudget) -> None:
        """Create or replace a tenant budget."""
        ...

    def tenant_budget(self, tenant_id: str) -> TenantBudget | None:
        """Look up a tenant's budget."""
        ...

    def budget_transaction(self) -> ContextManager[None]:
        """Serialize refresh, affordability decision, and reservation mutation."""
        ...

    @property
    def budget_transaction_authoritative(self) -> bool:
        """Whether the transaction covers every writer that can share this store."""
        ...

    def put_spend_reservation(self, reservation: SpendReservation) -> None:
        """Record a cost upper bound before the provider boundary."""
        ...

    def active_spend_reservations(self) -> list[SpendReservation]:
        """Return reservations that have no authoritative settlement."""
        ...

    def release_spend_reservation(self, reservation_id: str) -> bool:
        """Release a reservation after authoritative settlement."""
        ...

    def settle_spend_reservation(self, settlement: SpendSettlement) -> bool:
        """Close an active reservation with an operator settlement."""
        ...

    def spend_settlements(self) -> dict[str, SpendSettlement]:
        """Every operator settlement, keyed by reservation id."""
        ...


class InMemorySpendLedgerStore:
    """Process-local :class:`SpendLedgerStore`."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: list[MeteredUsage] = []
        self._record_ids: set[str] = set()
        self._keys: dict[str, VirtualKey] = {}
        self._budgets: dict[str, TenantBudget] = {}
        self._reservations: dict[str, SpendReservation] = {}
        self._settlements: dict[str, SpendSettlement] = {}

    @contextmanager
    def budget_transaction(self) -> Iterator[None]:
        """Serialize one admission decision and reservation mutation."""
        with self._lock:
            yield

    @property
    def budget_transaction_authoritative(self) -> bool:
        """A process-local store covers every writer that can access its state."""
        return True

    def append_usage(self, entry: MeteredUsage) -> bool:
        """Append one entry unless its usage record id is already stored."""
        with self._lock:
            record_id = entry.record.usage_record_id
            if record_id in self._record_ids:
                return False
            self._entries.append(entry)
            self._record_ids.add(record_id)
            return True

    def usage_entries(
        self, start: int | None = None, end: int | None = None
    ) -> list[MeteredUsage]:
        """Return entries in the half-open window."""
        with self._lock:
            return [
                entry
                for entry in self._entries
                if (start is None or entry.created_at >= start)
                and (end is None or entry.created_at < end)
            ]

    def put_virtual_key(self, key: VirtualKey) -> None:
        """Store a key definition by digest."""
        with self._lock:
            self._keys[key.key_hash] = key

    def virtual_key(self, key_hash: str) -> VirtualKey | None:
        """Return a key definition by digest."""
        with self._lock:
            return self._keys.get(key_hash)

    def virtual_keys(self) -> list[VirtualKey]:
        """Return all key definitions."""
        with self._lock:
            return list(self._keys.values())

    def put_tenant_budget(self, budget: TenantBudget) -> None:
        """Store a tenant budget."""
        with self._lock:
            self._budgets[budget.tenant_id] = budget

    def tenant_budget(self, tenant_id: str) -> TenantBudget | None:
        """Return a tenant budget."""
        with self._lock:
            return self._budgets.get(tenant_id)

    def put_spend_reservation(self, reservation: SpendReservation) -> None:
        """Store an active pre-call cost bound."""
        with self._lock:
            self._reservations[reservation.reservation_id] = reservation

    def active_spend_reservations(self) -> list[SpendReservation]:
        """Return every reservation not yet settled."""
        with self._lock:
            return list(self._reservations.values())

    def release_spend_reservation(self, reservation_id: str) -> bool:
        """Remove a reservation after authoritative settlement."""
        with self._lock:
            return self._reservations.pop(reservation_id, None) is not None

    def settle_spend_reservation(self, settlement: SpendSettlement) -> bool:
        """Replace an active reservation with an operator settlement."""
        with self._lock:
            if settlement.reservation_id not in self._reservations:
                return False
            self._reservations.pop(settlement.reservation_id)
            self._settlements[settlement.reservation_id] = settlement
            return True

    def spend_settlements(self) -> dict[str, SpendSettlement]:
        """Return every operator settlement keyed by reservation id."""
        with self._lock:
            return dict(self._settlements)


class JsonlSpendLedgerStore(InMemorySpendLedgerStore):
    """Durable append-only JSON Lines :class:`SpendLedgerStore`.

    Each line is one event: ``{"event": "usage" | "virtual_key" |
    "tenant_budget" | "spend_reservation" | "spend_release" |
    "spend_settlement", "data": {...}}``.
    Definitions are last-write-wins on replay. Active reservations survive a
    crash and therefore fail closed until explicit authoritative settlement.
    A POSIX file lock serializes cross-process budget transactions. The file
    is replayed on construction; an unterminated *final*
    line (a crash mid-write) is counted in :attr:`skipped_partial_lines` and
    moved to ``<name>.partial`` so later appends stay line-aligned, while a
    corrupt line anywhere else raises ``ValueError`` so lost spend is never
    silently under-counted. Writes are flushed and fsynced.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        super().__init__()
        self.path = Path(path)
        self.skipped_partial_lines = 0
        self._write_lock = threading.Lock()
        self._transaction_state = threading.local()
        self._budget_lock_path = Path(f"{self.path}.lock")
        if self.path.exists():
            with self.budget_transaction():
                pass

    def _in_budget_transaction(self) -> bool:
        return bool(getattr(self._transaction_state, "active", False))

    @property
    def budget_transaction_authoritative(self) -> bool:
        """POSIX flock is the cross-process authority for this adapter."""
        return fcntl is not None

    @contextmanager
    def budget_transaction(self) -> Iterator[None]:
        """Lock, refresh, then atomically decide and mutate across processes."""
        with self._lock:
            if self._in_budget_transaction():
                yield
                return
            if fcntl is None:
                self._transaction_state.active = True
                try:
                    self._reload()
                    yield
                finally:
                    self._transaction_state.active = False
                return
            self._budget_lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self._budget_lock_path.open("a+b") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                self._transaction_state.active = True
                try:
                    self._reload()
                    yield
                finally:
                    self._transaction_state.active = False
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _reload(self) -> None:
        """Rebuild the in-memory projection while holding the file lock."""
        self._entries.clear()
        self._record_ids.clear()
        self._keys.clear()
        self._budgets.clear()
        self._reservations.clear()
        self._settlements.clear()
        self.skipped_partial_lines = 0
        if self.path.exists():
            self._replay()

    def _replay(self) -> None:
        raw = self.path.read_bytes()
        lines = raw.decode("utf-8", errors="replace").splitlines()
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                self._apply(event)
            except (ValueError, KeyError, TypeError) as exc:
                if index == len(lines) - 1 and not raw.endswith(b"\n"):
                    self.skipped_partial_lines += 1
                    self._quarantine_partial_tail(raw)
                    continue
                raise ValueError(
                    f"corrupt spend ledger line {index + 1} in {self.path}"
                ) from exc

    def _quarantine_partial_tail(self, raw: bytes) -> None:
        """Move an unterminated final line aside so later appends start on a clean line.

        The fragment is kept next to the ledger (``<name>.partial``) as
        evidence; the ledger is truncated to its last complete line.
        """
        cut = raw.rfind(b"\n") + 1
        with open(f"{self.path}.partial", "ab") as evidence:
            evidence.write(raw[cut:] + b"\n")
        with self.path.open("r+b") as handle:
            handle.truncate(cut)
            handle.flush()
            os.fsync(handle.fileno())

    def _apply(self, event: dict[str, Any]) -> None:
        kind = event["event"]
        data = event["data"]
        if kind == "usage":
            super().append_usage(MeteredUsage.from_dict(data))
        elif kind == "virtual_key":
            super().put_virtual_key(VirtualKey.from_dict(data))
        elif kind == "tenant_budget":
            super().put_tenant_budget(TenantBudget.from_dict(data))
        elif kind == "spend_reservation":
            super().put_spend_reservation(SpendReservation.from_dict(data))
        elif kind == "spend_release":
            super().release_spend_reservation(data["reservation_id"])
        elif kind == "spend_settlement":
            super().settle_spend_reservation(SpendSettlement.from_dict(data))
        else:
            raise ValueError(f"unknown spend ledger event {kind!r}")

    def _write(self, kind: str, data: dict[str, Any]) -> None:
        if self._in_budget_transaction():
            self._write_unlocked(kind, data)
            return
        with self._write_lock:
            self._budget_lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self._budget_lock_path.open("a+b") as lock_handle:
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    self._write_unlocked(kind, data)
                finally:
                    if fcntl is not None:
                        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _write_unlocked(self, kind: str, data: dict[str, Any]) -> None:
        """Append one event while the caller owns the process/file lock."""
        line = json.dumps({"event": kind, "data": data}, sort_keys=True, separators=(",", ":"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def append_usage(self, entry: MeteredUsage) -> bool:
        """Persist, then index, one usage entry (duplicates are not rewritten)."""
        with self._lock:
            if entry.record.usage_record_id in self._record_ids:
                return False
            self._write("usage", entry.as_dict())
            return super().append_usage(entry)

    def put_virtual_key(self, key: VirtualKey) -> None:
        """Persist, then index, a key definition."""
        with self._lock:
            self._write("virtual_key", key.as_dict())
            super().put_virtual_key(key)

    def put_tenant_budget(self, budget: TenantBudget) -> None:
        """Persist, then index, a tenant budget."""
        with self._lock:
            self._write("tenant_budget", budget.as_dict())
            super().put_tenant_budget(budget)

    def put_spend_reservation(self, reservation: SpendReservation) -> None:
        """Persist, then index, one active cost upper bound."""
        with self._lock:
            self._write("spend_reservation", reservation.as_dict())
            super().put_spend_reservation(reservation)

    def release_spend_reservation(self, reservation_id: str) -> bool:
        """Persist settlement before removing an active reservation."""
        with self._lock:
            if reservation_id not in self._reservations:
                return False
            self._write("spend_release", {"reservation_id": reservation_id})
            return super().release_spend_reservation(reservation_id)

    def settle_spend_reservation(self, settlement: SpendSettlement) -> bool:
        """Refresh under the file lock, then persist an operator settlement."""
        with self._lock, self.budget_transaction():
            if settlement.reservation_id not in self._reservations:
                return False
            self._write("spend_settlement", settlement.as_dict())
            return super().settle_spend_reservation(settlement)


def spent_in_scope(
    entries: Iterable[MeteredUsage],
    *,
    scope: BudgetScope,
    scope_id: str,
    since: int | None,
    currency: str = "USD",
    settled_reservation_ids: Iterable[str] = (),
) -> tuple[Money, int]:
    """Sum charged cost for one budget scope since ``since``.

    Returns ``(spent, unpriced_calls)``. Entries whose cost is unknown are not
    summed (no invented prices) but are counted so callers can flag them.
    An unknown entry whose reservation an operator settled is neither summed
    nor counted here; :func:`settled_in_scope` adds the settled amount once.
    Entries in a different currency are skipped (no exchange-rate evidence).
    """
    settled = set(settled_reservation_ids)
    total = Money.zero(currency)
    unpriced = 0
    for entry in entries:
        if since is not None and entry.created_at < since:
            continue
        if scope is BudgetScope.TENANT and entry.tenant_id != scope_id:
            continue
        if scope is BudgetScope.VIRTUAL_KEY and entry.virtual_key_id != scope_id:
            continue
        if scope is BudgetScope.RUN and entry.run_id != scope_id:
            continue
        if entry.charged_cost is None:
            if entry.reservation_id is not None and entry.reservation_id in settled:
                continue
            unpriced += 1
            continue
        if entry.charged_cost.currency != total.currency:
            continue
        total = total + entry.charged_cost
    return total, unpriced


def reserved_in_scope(
    reservations: Iterable[SpendReservation],
    *,
    scope: BudgetScope,
    scope_id: str,
    since: int | None,
    currency: str = "USD",
) -> Money:
    """Sum active pre-call cost bounds for one budget scope and window.

    A reservation created before ``since`` (the start of a windowed budget's
    current period) no longer counts: an unknown-outcome reservation expires
    with the ``budget_duration`` window in which it was made. All-time
    budgets (``since is None``) keep it until an operator settlement.
    """
    total = Money.zero(currency)
    for reservation in reservations:
        if since is not None and reservation.created_at < since:
            continue
        if scope is BudgetScope.TENANT and reservation.tenant_id != scope_id:
            continue
        if scope is BudgetScope.VIRTUAL_KEY and reservation.virtual_key_id != scope_id:
            continue
        if scope is BudgetScope.RUN and reservation.run_id != scope_id:
            continue
        if reservation.reserved_cost.currency == total.currency:
            total = total + reservation.reserved_cost
    return total


def operator_settle_reservation(
    store: SpendLedgerStore,
    reservation_id: str,
    *,
    settled_cost: Money,
    reason: str,
    settled_by: str,
    now: int,
) -> SpendSettlement:
    """Close one active reservation with an explicit, reasoned operator settlement.

    This is the release path for an unknown provider outcome (ADR 0138): it
    appends a ``spend_settlement`` event that replaces the reservation and the
    linked unknown usage cost with ``settled_cost`` in every budget sum.
    Raises ``LookupError`` when the reservation is not active (already
    settled, released, or unknown) so a typo never writes a stray event.
    """
    with store.budget_transaction():
        reservation = next(
            (
                item
                for item in store.active_spend_reservations()
                if item.reservation_id == reservation_id
            ),
            None,
        )
        if reservation is None:
            raise LookupError(f"no active spend reservation {reservation_id!r}")
        settlement = SpendSettlement.for_reservation(
            reservation,
            settled_cost=settled_cost,
            settled_at=int(now),
            settled_by=settled_by,
            reason=reason,
        )
        if not store.settle_spend_reservation(settlement):
            raise LookupError(f"no active spend reservation {reservation_id!r}")
    return settlement


def active_reservation_report(store: SpendLedgerStore) -> list[dict[str, Any]]:
    """Describe every active reservation with its linked unknown-outcome calls."""
    with store.budget_transaction():
        reservations = store.active_spend_reservations()
        entries = store.usage_entries()
    linked: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if entry.reservation_id is None:
            continue
        linked.setdefault(entry.reservation_id, []).append(
            {
                "usage_record_id": entry.record.usage_record_id,
                "provider_name": entry.record.provider_name,
                "model_name": entry.record.model_name,
                "call_status": entry.call_status,
                "cost_source": entry.cost_source,
                "error_type": entry.error_type,
                "provider_status": entry.provider_status,
                "created_at": entry.created_at,
            }
        )
    return [
        {**reservation.as_dict(), "calls": linked.get(reservation.reservation_id, [])}
        for reservation in sorted(reservations, key=lambda item: item.created_at)
    ]


def settled_in_scope(
    settlements: Mapping[str, SpendSettlement] | Iterable[SpendSettlement],
    *,
    scope: BudgetScope,
    scope_id: str,
    since: int | None,
    currency: str = "USD",
) -> Money:
    """Sum operator-settled costs for one budget scope, windowed by reservation time."""
    items = settlements.values() if isinstance(settlements, Mapping) else settlements
    total = Money.zero(currency)
    for settlement in items:
        if since is not None and settlement.reserved_at < since:
            continue
        if scope is BudgetScope.TENANT and settlement.tenant_id != scope_id:
            continue
        if scope is BudgetScope.VIRTUAL_KEY and settlement.virtual_key_id != scope_id:
            continue
        if scope is BudgetScope.RUN and settlement.run_id != scope_id:
            continue
        if settlement.settled_cost.currency == total.currency:
            total = total + settlement.settled_cost
    return total


def aggregate_usage(
    entries: Iterable[MeteredUsage],
    *,
    group_by: tuple[str, ...] = ("tenant_id",),
    start: int | None = None,
    end: int | None = None,
) -> list[dict[str, Any]]:
    """Roll up usage by any of :data:`GROUP_BY_FIELDS` over an optional ``[start, end)`` window.

    Each row reports calls, token sums over measured calls, the charged cost
    per currency, and counts of unpriced and unmeasured calls so a total is
    never presented as complete when part of it is unknown.
    """
    unknown_fields = [name for name in group_by if name not in GROUP_BY_FIELDS]
    if unknown_fields or not group_by:
        raise ValueError(f"group_by must be a non-empty subset of {GROUP_BY_FIELDS}")
    rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    for entry in entries:
        if (start is not None and entry.created_at < start) or (
            end is not None and entry.created_at >= end
        ):
            continue
        values = {
            "tenant_id": entry.tenant_id,
            "virtual_key_id": entry.virtual_key_id,
            "provider_name": entry.record.provider_name,
            "model_name": entry.record.model_name,
            "run_id": entry.run_id,
            "call_status": entry.call_status,
        }
        currency = (
            entry.charged_cost.currency if entry.charged_cost is not None else "USD"
        )
        key = tuple(values[name] for name in group_by) + (currency,)
        row = rows.get(key)
        if row is None:
            row = {name: values[name] for name in group_by}
            row.update(
                {
                    "currency": currency,
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "_cost": Money.zero(currency),
                    "unpriced_calls": 0,
                    "unmeasured_calls": 0,
                }
            )
            rows[key] = row
        row["calls"] += 1
        if entry.record.measurement_status == "unavailable":
            row["unmeasured_calls"] += 1
        else:
            row["prompt_tokens"] += entry.record.prompt_tokens
            row["completion_tokens"] += entry.record.completion_tokens
        if entry.charged_cost is None:
            row["unpriced_calls"] += 1
        else:
            row["_cost"] = row["_cost"] + entry.charged_cost
    result = []
    for key in sorted(rows, key=lambda item: tuple("" if v is None else str(v) for v in item)):
        row = rows[key]
        cost = row.pop("_cost")
        row["charged_cost"] = cost.as_float()
        row["cost_complete"] = row["unpriced_calls"] == 0
        result.append(row)
    return result


def summarize_run(
    entries: Iterable[MeteredUsage],
    *,
    run_id: str,
    tenant_id: str,
    virtual_key_id: str | None = None,
    budget: dict[str, Any] | None = None,
    dropped_providers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the JSON run artifact: totals, per provider/model rows, and every call."""
    run_entries = [entry for entry in entries if entry.run_id == run_id]
    totals = aggregate_usage(run_entries, group_by=("run_id",)) if run_entries else []
    return {
        "schema": RUN_SUMMARY_SCHEMA,
        "run_id": run_id,
        "tenant_id": tenant_id,
        "virtual_key_id": virtual_key_id,
        "totals": totals,
        "by_provider_model": (
            aggregate_usage(run_entries, group_by=("provider_name", "model_name"))
            if run_entries
            else []
        ),
        "dropped_providers": dict(sorted((dropped_providers or {}).items())),
        "budget": budget or {},
        "calls": [entry.as_dict() for entry in run_entries],
    }


def write_run_usage_summary(path: str | os.PathLike[str], summary: dict[str, Any]) -> Path:
    """Atomically write a run summary JSON artifact and return its path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=".run-usage-", dir=str(target.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(summary, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return target


__all__ = [
    "CALL_STATUSES",
    "COST_SOURCES",
    "GROUP_BY_FIELDS",
    "InMemorySpendLedgerStore",
    "JsonlSpendLedgerStore",
    "MeteredUsage",
    "RUN_SUMMARY_SCHEMA",
    "SpendReservation",
    "SpendLedgerStore",
    "SpendSettlement",
    "active_reservation_report",
    "aggregate_usage",
    "operator_settle_reservation",
    "reserved_in_scope",
    "settled_in_scope",
    "spent_in_scope",
    "summarize_run",
    "write_run_usage_summary",
]
