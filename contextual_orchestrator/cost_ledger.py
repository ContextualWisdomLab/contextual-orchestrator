"""LLM usage + cost ledger with multi-dimensional attribution.

This module records **per-request** token usage and computed cost for every
completion the orchestrator serves — synchronous or batch — and rolls those
records up by any attribution dimension over any time window.

Attribution dimensions (all first-class, all reportable):

    account, service, upstream_api (provider), model_name, team, group, company

Design:

* Prices come from a configurable **price table** (``llm_price_entries``) that
  lives in the KV config store, not in ``os.getenv``. Cost is computed from
  prompt/completion token counts against that table.
* Records are written to the **usage ledger** (``llm_usage_records``). Two
  stores are provided: an always-available in-memory store (default, used by
  tests and the mock/local path) and a PEP-249 SQL store that works with the
  stdlib ``sqlite3`` module *and* ``psycopg`` — so the same schema runs
  standalone or against the Postgres the batch engine uses.
* :class:`CostLedger.rollup` aggregates cost + tokens grouped by any dimension,
  filtered by an optional ``[start, end)`` time window.

DB object names are two-or-more-word snake_case per the repository convention:
``llm_usage_records``, ``cost_attribution_dimensions``, ``llm_price_entries``,
``cost_attribution_values``, and ``usage_record_attributions``.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
import time
from typing import Any, Dict, List, Optional, Protocol
import uuid


# ---------------------------------------------------------------------------
# Attribution dimensions
# ---------------------------------------------------------------------------

# Ordered catalog of the attribution dimensions cost can be rolled up by. The
# first element of each tuple is the canonical dimension name used in report
# queries; the second is the human label; the third is the ledger column.
ATTRIBUTION_DIMENSION_CATALOG: tuple[tuple[str, str, str], ...] = (
    ("account", "Account", "account_name"),
    ("service", "Service", "service_name"),
    ("upstream_api", "Upstream API / provider", "upstream_api"),
    ("model_name", "Model name", "model_name"),
    ("team", "Team", "team_name"),
    ("group", "Group", "group_name"),
    ("company", "Company", "company_name"),
)

ATTRIBUTION_DIMENSIONS: tuple[str, ...] = tuple(
    name for name, _label, _column in ATTRIBUTION_DIMENSION_CATALOG
)

_DIMENSION_TO_COLUMN: Dict[str, str] = {
    name: column for name, _label, column in ATTRIBUTION_DIMENSION_CATALOG
}

# ``upstream_api`` is the provider; expose "provider" as an alias for reports.
_DIMENSION_TO_COLUMN["provider"] = "upstream_api"

UNATTRIBUTED = "unattributed"


@dataclass
class AttributionDimensions:
    """Multi-dimensional attribution for a single usage record."""

    account: str = UNATTRIBUTED
    service: str = UNATTRIBUTED
    upstream_api: str = UNATTRIBUTED
    model_name: str = UNATTRIBUTED
    team: str = UNATTRIBUTED
    group: str = UNATTRIBUTED
    company: str = UNATTRIBUTED

    @classmethod
    def from_mapping(cls, data: Optional[Dict[str, Any]]) -> "AttributionDimensions":
        """Build attribution from a loose mapping, ignoring unknown keys."""
        data = data or {}
        known = {name: str(data[name]) for name in ATTRIBUTION_DIMENSIONS if data.get(name)}
        # accept "provider" as an alias for the upstream API dimension
        if not known.get("upstream_api") and data.get("provider"):
            known["upstream_api"] = str(data["provider"])
        return cls(**known)

    def as_dict(self) -> Dict[str, str]:
        """Return the dimension values keyed by canonical dimension name."""
        return {name: getattr(self, name) for name in ATTRIBUTION_DIMENSIONS}


# ---------------------------------------------------------------------------
# Price table
# ---------------------------------------------------------------------------

_PRICE_CATEGORY = "llm_price_entries"


def _price_key(provider: str, model: str) -> str:
    return f"{provider}:{model}"


@dataclass
class PriceEntry:
    """A single price-table row: per-1K-token prices for a provider+model."""

    provider_name: str
    model_name: str
    prompt_price_per_1k: float
    completion_price_per_1k: float
    currency_code: str = "USD"

    def as_dict(self) -> Dict[str, Any]:
        """Serialize the price entry for KV storage / reporting."""
        return {
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "prompt_price_per_1k": self.prompt_price_per_1k,
            "completion_price_per_1k": self.completion_price_per_1k,
            "currency_code": self.currency_code,
        }


class PriceBook:
    """Configurable price table read from the KV config store.

    Entries live under the ``llm_price_entries`` category keyed by
    ``"{provider}:{model}"``. Cost is computed as::

        prompt_tokens/1000 * prompt_price_per_1k
      + completion_tokens/1000 * completion_price_per_1k

    Money math uses :class:`~decimal.Decimal` and rounds half-up to 6 dp so
    small per-request costs accumulate without float drift.
    """

    def __init__(self, config_store: Any, default_currency: str = "USD") -> None:
        self._config = config_store
        self.default_currency = default_currency

    def set_price(self, entry: PriceEntry) -> None:
        """Persist a price entry into the KV config store."""
        self._config.set(
            _PRICE_CATEGORY,
            _price_key(entry.provider_name, entry.model_name),
            entry.as_dict(),
        )

    def get_price(self, provider: str, model: str) -> Optional[PriceEntry]:
        """Return the price entry for ``provider``+``model``, if configured.

        Falls back to a provider-wildcard entry (``"{provider}:*"``) so a
        provider can set one default price for all of its models.
        """
        raw = self._config.get(_PRICE_CATEGORY, _price_key(provider, model), None)
        if raw is None:
            raw = self._config.get(_PRICE_CATEGORY, _price_key(provider, "*"), None)
        if raw is None:
            return None
        return PriceEntry(
            provider_name=raw.get("provider_name", provider),
            model_name=raw.get("model_name", model),
            prompt_price_per_1k=float(raw.get("prompt_price_per_1k", 0.0)),
            completion_price_per_1k=float(raw.get("completion_price_per_1k", 0.0)),
            currency_code=raw.get("currency_code", self.default_currency),
        )

    def compute_cost(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> tuple[float, str]:
        """Return ``(cost_amount, currency_code)`` for a request.

        An unpriced provider/model yields ``0.0`` in the default currency so
        recording never fails on a missing price row.
        """
        entry = self.get_price(provider, model)
        if entry is None:
            return 0.0, self.default_currency
        prompt_cost = (Decimal(prompt_tokens) / Decimal(1000)) * Decimal(
            str(entry.prompt_price_per_1k)
        )
        completion_cost = (Decimal(completion_tokens) / Decimal(1000)) * Decimal(
            str(entry.completion_price_per_1k)
        )
        total = (prompt_cost + completion_cost).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
        return float(total), entry.currency_code


# ---------------------------------------------------------------------------
# Usage records + stores
# ---------------------------------------------------------------------------


@dataclass
class UsageRecord:
    """One recorded completion: tokens, cost, and full attribution."""

    usage_record_id: str
    created_at: int
    workflow_run_id: Optional[str]
    request_channel: str  # "sync" | "batch"
    route_mode: Optional[str]  # "route" | "conduct"
    provider_name: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_amount: float
    currency_code: str
    attribution: AttributionDimensions = field(default_factory=AttributionDimensions)

    def as_dict(self) -> Dict[str, Any]:
        """Flatten the record for JSON and backward-compatible report output."""
        # Execution identity is evidence of what ran — never a client-chosen tag.
        # Account/service/team/group/company remain descriptive attribution.
        row = {
            "usage_record_id": self.usage_record_id,
            "created_at": self.created_at,
            "workflow_run_id": self.workflow_run_id,
            "request_channel": self.request_channel,
            "route_mode": self.route_mode,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_amount": self.cost_amount,
            "currency_code": self.currency_code,
        }
        row.update(
            {
                "account_name": self.attribution.account,
                "service_name": self.attribution.service,
                "upstream_api": self.attribution.upstream_api,
                "team_name": self.attribution.team,
                "group_name": self.attribution.group,
                "company_name": self.attribution.company,
            }
        )
        return row


class LedgerStore(Protocol):
    """Storage contract for usage records."""

    def append(self, record: UsageRecord) -> None:
        """Persist a usage record."""
        ...

    def query(self, start: Optional[int], end: Optional[int]) -> List[Dict[str, Any]]:
        """Return record rows created in ``[start, end)`` (``None`` = unbounded)."""
        ...


@dataclass(frozen=True)
class UsageTelemetryEvent:
    """OpenTelemetry-shaped usage event without prompt or answer content."""

    name: str
    attributes: Dict[str, Any]
    metrics: Dict[str, float]
    status: str = "ok"
    error_type: Optional[str] = None

    @classmethod
    def from_record(
        cls,
        record: UsageRecord,
        *,
        export_state: str,
        error_type: Optional[str] = None,
    ) -> "UsageTelemetryEvent":
        """Build a prompt-safe usage telemetry event from a ledger record."""
        attributes: Dict[str, Any] = {
            "gen_ai.system": record.provider_name or "unknown",
            "gen_ai.operation.name": "chat.completions",
            "gen_ai.request.model": record.model_name,
            "gen_ai.response.model": record.model_name,
            "contextual_orchestrator.usage_record_id": record.usage_record_id,
            "contextual_orchestrator.request_channel": record.request_channel,
            "contextual_orchestrator.usage.export_state": export_state,
        }
        if record.workflow_run_id:
            attributes["contextual_orchestrator.workflow_run_id"] = record.workflow_run_id
        if record.route_mode:
            attributes["contextual_orchestrator.route_mode"] = record.route_mode
        for name, value in record.attribution.as_dict().items():
            attributes[f"contextual_orchestrator.attribution.{name}"] = value
        if error_type:
            attributes["error.type"] = error_type

        metrics = {
            "gen_ai.usage.input_tokens": float(record.prompt_tokens),
            "gen_ai.usage.output_tokens": float(record.completion_tokens),
            "gen_ai.usage.total_tokens": float(record.total_tokens),
            "gen_ai.usage.cost": float(record.cost_amount),
            "contextual_orchestrator.usage.records": 1.0,
        }
        if error_type:
            metrics["contextual_orchestrator.usage.export_failures"] = 1.0
        return cls(
            name="gen_ai.client.usage",
            attributes=attributes,
            metrics=metrics,
            status="error" if error_type else "ok",
            error_type=error_type,
        )


class UsageTelemetrySink(Protocol):
    """Sink contract for prompt-safe usage telemetry."""

    def emit_usage(self, event: UsageTelemetryEvent) -> None:
        """Emit one usage telemetry event."""
        ...


class NoopUsageTelemetrySink:
    """Default sink for callers that do not wire telemetry yet."""

    def emit_usage(self, event: UsageTelemetryEvent) -> None:
        return None


class InMemoryUsageTelemetrySink:
    """Small test/operator sink that keeps recent prompt-safe usage events."""

    def __init__(self, max_events: int = 512) -> None:
        self._max_events = max_events
        self._events: List[UsageTelemetryEvent] = []
        self._lock = threading.Lock()

    def emit_usage(self, event: UsageTelemetryEvent) -> None:
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                del self._events[: len(self._events) - self._max_events]

    def events(self) -> List[UsageTelemetryEvent]:
        with self._lock:
            return list(self._events)


@dataclass
class UsageTelemetryHealth:
    """Health counters for usage ledger export, safe for operator surfaces."""

    records_accepted: int = 0
    records_stored: int = 0
    records_dropped: int = 0
    store_failures: int = 0
    last_error_type: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "records_accepted": self.records_accepted,
            "records_stored": self.records_stored,
            "records_dropped": self.records_dropped,
            "store_failures": self.store_failures,
            "last_error_type": self.last_error_type,
        }


def _emit_usage_event(
    sink: UsageTelemetrySink,
    event: UsageTelemetryEvent,
) -> None:
    try:
        sink.emit_usage(event)
    except Exception:
        # Telemetry export is best-effort and must not affect completions.
        return None


class NonBlockingLedgerStore:
    """Ledger store wrapper that keeps persistence out of the request path."""

    def __init__(
        self,
        backend: LedgerStore,
        *,
        queue_size: int = 1000,
        telemetry_sink: Optional[UsageTelemetrySink] = None,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be at least 1")
        self.backend = backend
        self._telemetry_sink = telemetry_sink or NoopUsageTelemetrySink()
        self._queue: queue.Queue[UsageRecord] = queue.Queue(maxsize=queue_size)
        self._health = UsageTelemetryHealth()
        self._lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._run,
            name="contextual-orchestrator-usage-ledger",
            daemon=True,
        )
        self._worker.start()

    def append(self, record: UsageRecord) -> None:
        """Queue a record for background persistence without blocking."""
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            self._mark("records_dropped", error_type="queue.Full")
            _emit_usage_event(
                self._telemetry_sink,
                UsageTelemetryEvent.from_record(
                    record,
                    export_state="dropped",
                    error_type="queue.Full",
                ),
            )
            return
        self._mark("records_accepted")
        _emit_usage_event(
            self._telemetry_sink,
            UsageTelemetryEvent.from_record(record, export_state="queued"),
        )

    def query(self, start: Optional[int] = None, end: Optional[int] = None) -> List[Dict[str, Any]]:
        """Query the backing store; queued writes may still be in flight."""
        return self.backend.query(start, end)

    def flush(self, timeout: Optional[float] = None) -> bool:
        """Wait for queued writes to finish. Returns ``False`` on timeout."""
        deadline = time.monotonic() + timeout if timeout is not None else None
        while self._queue.unfinished_tasks:
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def telemetry_health(self) -> Dict[str, Any]:
        with self._lock:
            return self._health.as_dict()

    def _run(self) -> None:
        while True:
            record = self._queue.get()
            try:
                self.backend.append(record)
            except Exception as exc:
                error_type = type(exc).__name__
                self._mark("store_failures", error_type=error_type)
                _emit_usage_event(
                    self._telemetry_sink,
                    UsageTelemetryEvent.from_record(
                        record,
                        export_state="export_error",
                        error_type=error_type,
                    ),
                )
            else:
                self._mark("records_stored")
                _emit_usage_event(
                    self._telemetry_sink,
                    UsageTelemetryEvent.from_record(record, export_state="stored"),
                )
            finally:
                self._queue.task_done()

    def _mark(self, field_name: str, error_type: Optional[str] = None) -> None:
        with self._lock:
            setattr(self._health, field_name, getattr(self._health, field_name) + 1)
            if error_type:
                self._health.last_error_type = error_type


class InMemoryLedgerStore:
    """Dependency-free ledger store backed by a list (default)."""

    def __init__(self) -> None:
        self._rows: List[Dict[str, Any]] = []

    def append(self, record: UsageRecord) -> None:
        """Append a flattened record row."""
        self._rows.append(record.as_dict())

    def query(self, start: Optional[int] = None, end: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return rows within the optional half-open time window."""
        return [row for row in self._rows if _within_window(row["created_at"], start, end)]

    def __len__(self) -> int:
        return len(self._rows)


# Portable DDL for the normalized ledger objects. Runs on stdlib sqlite3 and
# psycopg. Execution identity stays on the usage row; descriptive attribution
# values are stored once and linked through a composite key.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cost_attribution_dimensions (
    dimension_name  TEXT PRIMARY KEY,
    dimension_label TEXT NOT NULL,
    dimension_order INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_price_entries (
    price_entry_id          TEXT PRIMARY KEY,
    provider_name           TEXT NOT NULL,
    model_name              TEXT NOT NULL,
    prompt_price_per_1k     REAL NOT NULL,
    completion_price_per_1k REAL NOT NULL,
    currency_code           TEXT NOT NULL DEFAULT 'USD',
    updated_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_usage_records (
    usage_record_id   TEXT PRIMARY KEY,
    created_at        INTEGER NOT NULL,
    workflow_run_id   TEXT,
    request_channel   TEXT NOT NULL,
    route_mode        TEXT,
    provider_name     TEXT,
    model_name        TEXT,
    prompt_tokens     INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens      INTEGER NOT NULL,
    cost_amount       REAL NOT NULL,
    currency_code     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_attribution_values (
    dimension_name  TEXT NOT NULL,
    dimension_value TEXT NOT NULL,
    CONSTRAINT cost_attribution_values_primary_key
        PRIMARY KEY (dimension_name, dimension_value),
    CONSTRAINT cost_attribution_values_dimension_foreign_key
        FOREIGN KEY (dimension_name) REFERENCES cost_attribution_dimensions(dimension_name)
);

CREATE TABLE IF NOT EXISTS usage_record_attributions (
    usage_record_id TEXT NOT NULL,
    dimension_name  TEXT NOT NULL,
    dimension_value TEXT NOT NULL,
    CONSTRAINT usage_record_attributions_primary_key
        PRIMARY KEY (usage_record_id, dimension_name),
    CONSTRAINT usage_record_attributions_record_foreign_key
        FOREIGN KEY (usage_record_id) REFERENCES llm_usage_records(usage_record_id)
        ON DELETE CASCADE,
    CONSTRAINT usage_record_attributions_value_foreign_key
        FOREIGN KEY (dimension_name, dimension_value)
        REFERENCES cost_attribution_values(dimension_name, dimension_value)
);
"""

_CORE_USAGE_COLUMNS = (
    "usage_record_id",
    "created_at",
    "workflow_run_id",
    "request_channel",
    "route_mode",
    "provider_name",
    "model_name",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_amount",
    "currency_code",
)
_USAGE_COLUMNS = (
    "usage_record_id",
    "created_at",
    "workflow_run_id",
    "request_channel",
    "route_mode",
    "provider_name",
    "model_name",
    "account_name",
    "service_name",
    "upstream_api",
    "team_name",
    "group_name",
    "company_name",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_amount",
    "currency_code",
)
_RELATIONAL_ATTRIBUTION_COLUMNS = {
    "account": "account_name",
    "service": "service_name",
    "team": "team_name",
    "group": "group_name",
    "company": "company_name",
}
_LEGACY_ATTRIBUTION_COLUMNS = (
    "account_name",
    "service_name",
    "upstream_api",
    "team_name",
    "group_name",
    "company_name",
)
_LEGACY_USAGE_SELECT_SQL = (
    "SELECT usage_record_id, created_at, workflow_run_id, request_channel, route_mode, "
    "provider_name, model_name, prompt_tokens, completion_tokens, total_tokens, "
    "cost_amount, currency_code, account_name, service_name, upstream_api, "
    "team_name, group_name, company_name FROM llm_usage_records_legacy"
)
_DIMENSION_SELECT_SQL = {
    "qmark": "SELECT 1 FROM cost_attribution_dimensions WHERE dimension_name = ?",
    "pyformat": "SELECT 1 FROM cost_attribution_dimensions WHERE dimension_name = %s",
}
_DIMENSION_INSERT_SQL = {
    "qmark": (
        "INSERT INTO cost_attribution_dimensions "
        "(dimension_name, dimension_label, dimension_order) VALUES (?, ?, ?)"
    ),
    "pyformat": (
        "INSERT INTO cost_attribution_dimensions "
        "(dimension_name, dimension_label, dimension_order) VALUES (%s, %s, %s)"
    ),
}
_CORE_USAGE_INSERT_SQL = {
    "qmark": (
        "INSERT INTO llm_usage_records "
        "(usage_record_id, created_at, workflow_run_id, request_channel, "
        "route_mode, provider_name, model_name, prompt_tokens, completion_tokens, "
        "total_tokens, cost_amount, currency_code) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    ),
    "pyformat": (
        "INSERT INTO llm_usage_records "
        "(usage_record_id, created_at, workflow_run_id, request_channel, "
        "route_mode, provider_name, model_name, prompt_tokens, completion_tokens, "
        "total_tokens, cost_amount, currency_code) VALUES "
        "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    ),
}
_ATTRIBUTION_VALUE_INSERT_SQL = {
    style: (
        "INSERT INTO cost_attribution_values (dimension_name, dimension_value) "
        f"VALUES ({placeholder}, {placeholder}) "
        "ON CONFLICT (dimension_name, dimension_value) DO NOTHING"
    )
    for style, placeholder in (("qmark", "?"), ("pyformat", "%s"))
}
_RECORD_ATTRIBUTION_INSERT_SQL = {
    style: (
        "INSERT INTO usage_record_attributions "
        "(usage_record_id, dimension_name, dimension_value) "
        f"VALUES ({placeholder}, {placeholder}, {placeholder}) "
        "ON CONFLICT (usage_record_id, dimension_name) DO UPDATE SET "
        "dimension_value = excluded.dimension_value"
    )
    for style, placeholder in (("qmark", "?"), ("pyformat", "%s"))
}
_USAGE_SELECT_SQL = (
    "SELECT u.usage_record_id, u.created_at, u.workflow_run_id, u.request_channel, "
    "u.route_mode, u.provider_name, u.model_name, "
    "COALESCE(MAX(CASE WHEN a.dimension_name = 'account' THEN a.dimension_value END), 'unattributed') AS account_name, "
    "COALESCE(MAX(CASE WHEN a.dimension_name = 'service' THEN a.dimension_value END), 'unattributed') AS service_name, "
    "u.provider_name AS upstream_api, "
    "COALESCE(MAX(CASE WHEN a.dimension_name = 'team' THEN a.dimension_value END), 'unattributed') AS team_name, "
    "COALESCE(MAX(CASE WHEN a.dimension_name = 'group' THEN a.dimension_value END), 'unattributed') AS group_name, "
    "COALESCE(MAX(CASE WHEN a.dimension_name = 'company' THEN a.dimension_value END), 'unattributed') AS company_name, "
    "u.prompt_tokens, u.completion_tokens, u.total_tokens, u.cost_amount, u.currency_code "
    "FROM llm_usage_records AS u "
    "LEFT JOIN usage_record_attributions AS a ON a.usage_record_id = u.usage_record_id"
)
_USAGE_GROUP_ORDER_SQL = (
    " GROUP BY u.usage_record_id, u.created_at, u.workflow_run_id, u.request_channel, "
    "u.route_mode, u.provider_name, u.model_name, u.prompt_tokens, "
    "u.completion_tokens, u.total_tokens, u.cost_amount, u.currency_code "
    "ORDER BY u.created_at, u.usage_record_id"
)
_USAGE_QUERY_SQL = {
    (style, has_start, has_end): f"{_USAGE_SELECT_SQL}{where}{_USAGE_GROUP_ORDER_SQL}"
    for style, placeholder in (("qmark", "?"), ("pyformat", "%s"))
    for has_start, has_end, where in (
        (False, False, ""),
        (True, False, f" WHERE u.created_at >= {placeholder}"),
        (False, True, f" WHERE u.created_at < {placeholder}"),
        (True, True, f" WHERE u.created_at >= {placeholder} AND u.created_at < {placeholder}"),
    )
}


# A fixed, literal PRAGMA per known table -- never built from the ``table_name``
# argument -- so ``_table_columns`` cannot become a dynamic-identifier SQL
# interpolation seam even if a future caller passes an unexpected value.
_QMARK_TABLE_INFO_SQL = {
    "llm_usage_records": "PRAGMA table_info(llm_usage_records)",
}


class SqlLedgerStore:
    """PEP-249 SQL ledger store (stdlib ``sqlite3`` or ``psycopg``).

    Pass an open DB-API connection and a ``paramstyle`` matching the driver
    (``"qmark"`` for sqlite3, ``"pyformat"`` for psycopg). The schema is created
    on construction; the same DDL runs on either engine.
    """

    def __init__(self, connection: Any, paramstyle: str = "qmark") -> None:
        if paramstyle not in ("qmark", "pyformat"):
            raise ValueError("paramstyle must be qmark or pyformat")
        self._conn = connection
        self._paramstyle = paramstyle
        if self._paramstyle == "qmark":
            # sqlite3 keeps foreign-key enforcement per connection and defaults
            # it off. Set it before schema work can open a transaction.
            self._conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema()
        self._seed_dimension_catalog()

    def _table_columns(self, table_name: str) -> set[str]:
        """Return table columns while keeping identifier interpolation constant."""
        cur = self._conn.cursor()
        if self._paramstyle == "qmark":
            try:
                pragma_sql = _QMARK_TABLE_INFO_SQL[table_name]
            except KeyError:
                raise ValueError(f"unsupported qmark table for _table_columns: {table_name!r}") from None
            cur.execute(pragma_sql)
            return {row[1] for row in cur.fetchall()}
        # A PostgreSQL error aborts the current transaction, so never probe it
        # with SQLite syntax and then attempt a fallback on the same connection.
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s",
            (table_name,),
        )
        return {row[0] for row in cur.fetchall()}

    def _execute_schema(self) -> None:
        """Create the catalog, core ledger, and normalized attribution tables."""
        cur = self._conn.cursor()
        for statement in SCHEMA_SQL.strip().split(";"):
            if statement.strip():
                cur.execute(statement)

    def _insert_normalized_attribution(self, cur: Any, row: Dict[str, Any]) -> None:
        """Insert the five descriptive dimensions referenced by one usage row."""
        for dimension_name, column_name in _RELATIONAL_ATTRIBUTION_COLUMNS.items():
            dimension_value = row[column_name] or UNATTRIBUTED
            cur.execute(
                _ATTRIBUTION_VALUE_INSERT_SQL[self._paramstyle],
                (dimension_name, dimension_value),
            )
            cur.execute(
                _RECORD_ATTRIBUTION_INSERT_SQL[self._paramstyle],
                (row["usage_record_id"], dimension_name, dimension_value),
            )

    def _migrate_legacy_usage_table(self) -> None:
        """Move flattened legacy rows into the normalized schema transactionally."""
        cur = self._conn.cursor()
        try:
            cur.execute("ALTER TABLE llm_usage_records RENAME TO llm_usage_records_legacy")
        except Exception as exc:
            raise RuntimeError("legacy usage-table migration is ambiguous") from exc
        self._execute_schema()
        cur.execute(_LEGACY_USAGE_SELECT_SQL)
        legacy_rows = cur.fetchall()
        for values in legacy_rows:
            row = dict(zip((*_CORE_USAGE_COLUMNS, *_LEGACY_ATTRIBUTION_COLUMNS), values))
            cur.execute(
                _CORE_USAGE_INSERT_SQL[self._paramstyle],
                tuple(row[column] for column in _CORE_USAGE_COLUMNS),
            )
            self._insert_normalized_attribution(cur, row)
        cur.execute("DROP TABLE llm_usage_records_legacy")

    def _create_schema(self) -> None:
        """Create or migrate the ledger and roll back any partial DDL."""
        try:
            self._create_schema_in_transaction()
        except Exception:
            rollback = getattr(self._conn, "rollback", None)
            if callable(rollback):
                rollback()
            raise

    def _create_schema_in_transaction(self) -> None:
        """Apply schema creation and migration statements before commit."""
        statements = [statement for statement in SCHEMA_SQL.strip().split(";") if statement.strip()]
        cur = self._conn.cursor()
        # SQLite's legacy transaction mode does not begin a transaction for
        # DDL. Start one before any catalog DDL so a failed legacy migration
        # rolls back the rename, schema creation, copied rows, and cleanup as
        # one unit. PEP-249 connections may already have an active transaction.
        if not getattr(self._conn, "in_transaction", False):
            cur.execute("BEGIN")
        # Create the independent catalog tables first. Deferring the usage and
        # child tables keeps a legacy-table rename from leaving child FKs aimed
        # at the temporary legacy name.
        for statement in statements[:2]:
            cur.execute(statement)
        self._seed_dimension_catalog_in_transaction(cur)
        columns = self._table_columns("llm_usage_records")
        if not columns:
            for statement in statements[2:]:
                cur.execute(statement)
        elif "account_name" in columns:
            self._migrate_legacy_usage_table()
        elif not set(_CORE_USAGE_COLUMNS).issubset(columns):
            missing = ", ".join(sorted(set(_CORE_USAGE_COLUMNS) - columns))
            raise RuntimeError(f"unsupported usage ledger schema; missing columns: {missing}")
        else:
            for statement in statements[2:]:
                cur.execute(statement)
        self._conn.commit()

    def _seed_dimension_catalog(self) -> None:
        self._seed_dimension_catalog_in_transaction(self._conn.cursor())
        self._conn.commit()

    def _seed_dimension_catalog_in_transaction(self, cur: Any) -> None:
        """Seed dimension parents before child rows without committing an outer transaction."""
        for order, (name, label, _column) in enumerate(ATTRIBUTION_DIMENSION_CATALOG):
            cur.execute(
                _DIMENSION_SELECT_SQL[self._paramstyle],
                (name,),
            )
            if cur.fetchone() is None:
                cur.execute(
                    _DIMENSION_INSERT_SQL[self._paramstyle],
                    (name, label, order),
                )

    def append(self, record: UsageRecord) -> None:
        """Insert a usage record row."""
        row = record.as_dict()
        cur = self._conn.cursor()
        try:
            cur.execute(
                _CORE_USAGE_INSERT_SQL[self._paramstyle],
                tuple(row.get(column) for column in _CORE_USAGE_COLUMNS),
            )
            self._insert_normalized_attribution(cur, row)
            self._conn.commit()
        except Exception:
            rollback = getattr(self._conn, "rollback", None)
            if callable(rollback):
                rollback()
            raise

    def query(self, start: Optional[int] = None, end: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return record rows in the optional half-open window."""
        params: List[Any] = []
        if start is not None:
            params.append(start)
        if end is not None:
            params.append(end)
        cur = self._conn.cursor()
        cur.execute(
            _USAGE_QUERY_SQL[(self._paramstyle, start is not None, end is not None)],
            tuple(params),
        )
        return [dict(zip(_USAGE_COLUMNS, values)) for values in cur.fetchall()]


def _within_window(created_at: int, start: Optional[int], end: Optional[int]) -> bool:
    if start is not None and created_at < start:
        return False
    if end is not None and created_at >= end:
        return False
    return True


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


class CostLedger:
    """Records per-request usage + cost and rolls it up by any dimension."""

    def __init__(
        self,
        price_book: PriceBook,
        store: Optional[LedgerStore] = None,
        clock: Any = None,
        telemetry_sink: Optional[UsageTelemetrySink] = None,
        non_blocking_store: Optional[bool] = None,
        store_queue_size: int = 1000,
    ) -> None:
        self.price_book = price_book
        self.telemetry_sink = telemetry_sink or NoopUsageTelemetrySink()
        base_store = store or InMemoryLedgerStore()
        should_wrap = bool(non_blocking_store)
        if should_wrap:
            self.store: LedgerStore = NonBlockingLedgerStore(
                base_store,
                queue_size=store_queue_size,
                telemetry_sink=self.telemetry_sink,
            )
        else:
            self.store = base_store
        self._inline_health = UsageTelemetryHealth()
        self._clock = clock or (lambda: int(time.time()))

    def record_usage(
        self,
        *,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        request_channel: str = "sync",
        route_mode: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        attribution: Optional[AttributionDimensions | Dict[str, Any]] = None,
        created_at: Optional[int] = None,
    ) -> UsageRecord:
        """Compute cost, build a :class:`UsageRecord`, persist it, and return it."""
        if isinstance(attribution, dict) or attribution is None:
            # Strip caller-controlled execution identity before mapping so a
            # client cannot spoof model/provider rollups (buyer-bill honesty).
            if isinstance(attribution, dict):
                cleaned = {
                    key: value
                    for key, value in attribution.items()
                    if key not in {"model_name", "provider", "upstream_api"}
                }
            else:
                cleaned = None
            dims = AttributionDimensions.from_mapping(cleaned)
        else:
            dims = AttributionDimensions(
                account=attribution.account,
                service=attribution.service,
                upstream_api=UNATTRIBUTED,
                model_name=UNATTRIBUTED,
                team=attribution.team,
                group=attribution.group,
                company=attribution.company,
            )
        # Execution identity always wins — descriptive dimensions stay as-is.
        if model:
            dims.model_name = model
        if provider:
            dims.upstream_api = provider

        cost_amount, currency = self.price_book.compute_cost(
            provider, model, prompt_tokens, completion_tokens
        )
        record = UsageRecord(
            usage_record_id=f"usage_{uuid.uuid4().hex}",
            created_at=created_at if created_at is not None else self._clock(),
            workflow_run_id=workflow_run_id,
            request_channel=request_channel,
            route_mode=route_mode,
            provider_name=provider,
            model_name=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_amount=cost_amount,
            currency_code=currency,
            attribution=dims,
        )
        try:
            self.store.append(record)
        except Exception as exc:
            self._mark_inline_failure(type(exc).__name__)
            _emit_usage_event(
                self.telemetry_sink,
                UsageTelemetryEvent.from_record(
                    record,
                    export_state="export_error",
                    error_type=type(exc).__name__,
                ),
            )
        else:
            if not isinstance(self.store, NonBlockingLedgerStore):
                self._mark_inline_success()
                _emit_usage_event(
                    self.telemetry_sink,
                    UsageTelemetryEvent.from_record(record, export_state="stored"),
                )
        return record

    def flush(self, timeout: Optional[float] = None) -> bool:
        """Wait for pending non-blocking usage writes, if any."""
        flush = getattr(self.store, "flush", None)
        if callable(flush):
            return bool(flush(timeout=timeout))
        return True

    def telemetry_health(self) -> Dict[str, Any]:
        """Return prompt-safe ledger export health counters."""
        health = self._inline_health.as_dict()
        store_health = getattr(self.store, "telemetry_health", None)
        if callable(store_health):
            for key, value in store_health().items():
                if isinstance(value, int):
                    health[key] = int(health.get(key, 0)) + value
                elif value:
                    health[key] = value
        return health

    def rollup(
        self,
        dimension: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Aggregate cost + tokens grouped by ``dimension`` over ``[start, end)``.

        ``dimension`` is one of the attribution dimension names (``account``,
        ``service``, ``upstream_api``/``provider``, ``model_name``, ``team``,
        ``group``, ``company``). Returns a mapping of dimension value to totals.
        """
        column = _DIMENSION_TO_COLUMN.get(dimension)
        if column is None:
            raise ValueError(
                f"unknown attribution dimension {dimension!r}; "
                f"valid dimensions: {', '.join(ATTRIBUTION_DIMENSIONS)}"
            )
        buckets: Dict[str, Dict[str, Any]] = {}
        for row in self.store.query(start, end):
            key = row.get(column) or UNATTRIBUTED
            bucket = buckets.setdefault(
                key,
                {
                    "dimension": dimension,
                    "dimension_value": key,
                    "record_count": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_amount": Decimal("0"),
                    "currency_code": row.get("currency_code", "USD"),
                },
            )
            bucket["record_count"] += 1
            bucket["prompt_tokens"] += int(row.get("prompt_tokens", 0))
            bucket["completion_tokens"] += int(row.get("completion_tokens", 0))
            bucket["total_tokens"] += int(row.get("total_tokens", 0))
            bucket["cost_amount"] += Decimal(str(row.get("cost_amount", 0)))
        for bucket in buckets.values():
            bucket["cost_amount"] = float(
                bucket["cost_amount"].quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            )
        return buckets

    def report(
        self,
        dimension: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return a report envelope: per-value rollup plus a grand total."""
        buckets = self.rollup(dimension, start, end)
        items = sorted(
            buckets.values(), key=lambda item: item["cost_amount"], reverse=True
        )
        grand_total = self.total(start, end)
        return {
            "dimension": dimension,
            "time_window": {"start": start, "end": end},
            "items": items,
            "grand_total": grand_total,
        }

    def total(self, start: Optional[int] = None, end: Optional[int] = None) -> Dict[str, Any]:
        """Return grand totals (cost + tokens + record count) over the window."""
        rows = self.store.query(start, end)
        cost = sum((Decimal(str(row.get("cost_amount", 0))) for row in rows), Decimal("0"))
        return {
            "record_count": len(rows),
            "prompt_tokens": sum(int(row.get("prompt_tokens", 0)) for row in rows),
            "completion_tokens": sum(int(row.get("completion_tokens", 0)) for row in rows),
            "total_tokens": sum(int(row.get("total_tokens", 0)) for row in rows),
            "cost_amount": float(cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        }

    def records(self, start: Optional[int] = None, end: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return raw usage record rows in the optional window."""
        return self.store.query(start, end)

    def _mark_inline_success(self) -> None:
        self._inline_health.records_accepted += 1
        self._inline_health.records_stored += 1

    def _mark_inline_failure(self, error_type: str) -> None:
        self._inline_health.records_accepted += 1
        self._inline_health.store_failures += 1
        self._inline_health.last_error_type = error_type


def dimension_catalog() -> List[Dict[str, Any]]:
    """Return the attribution dimension catalog (name, label, column, order)."""
    return [
        {"dimension_name": name, "dimension_label": label, "ledger_column": column, "dimension_order": order}
        for order, (name, label, column) in enumerate(ATTRIBUTION_DIMENSION_CATALOG)
    ]
