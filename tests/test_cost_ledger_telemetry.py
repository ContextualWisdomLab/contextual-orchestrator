"""Telemetry, non-blocking, and inline-failure branches of the cost ledger.

Covers the best-effort telemetry emit + FIFO buffer eviction, the queue-full
drop and flush-timeout paths, the non-blocking worker persistence + emit path,
inline store-failure handling, the in-memory store length, and the SQL
half-open time-window WHERE clauses — all on stdlib fakes, no Postgres.
"""

from __future__ import annotations

from pathlib import Path
import queue as queue_mod
import sqlite3
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.cost_ledger import (  # noqa: E402
    AttributionDimensions,
    CostLedger,
    InMemoryLedgerStore,
    InMemoryUsageTelemetrySink,
    NonBlockingLedgerStore,
    PriceBook,
    PriceEntry,
    SqlLedgerStore,
    UsageTelemetryEvent,
    _emit_usage_event,
)
from contextual_orchestrator.kv_config import InMemoryConfigStore  # noqa: E402

_EXPORT_STATE_KEY = "contextual_orchestrator.usage.export_state"


def _ledger(store=None, **kwargs) -> CostLedger:
    """Build a priced ledger backed by the given store (in-memory by default)."""
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(
        PriceEntry("openai", "gpt-x", prompt_price_per_1k=2.0, completion_price_per_1k=4.0)
    )
    return CostLedger(price_book, store=store, **kwargs)


def _one_record(ledger: CostLedger | None = None):
    """Persist and return a single usage record through an inline ledger."""
    ledger = ledger or _ledger()
    return ledger.record_usage(
        provider="openai", model="gpt-x", prompt_tokens=10, completion_tokens=5
    )


def _export_states(sink: InMemoryUsageTelemetrySink):
    """Return the export_state of every event the sink captured."""
    return [event.attributes.get(_EXPORT_STATE_KEY) for event in sink.events()]


class _RaisingSink:
    """Telemetry sink whose emit always raises, proving emit is best-effort."""

    def emit_usage(self, event) -> None:
        """Always fail, so callers must swallow the error."""
        raise RuntimeError("telemetry backend down")


class _AlwaysFullQueue:
    """Fake queue that rejects every put and never drains.

    Implements the full interface the ``NonBlockingLedgerStore`` background
    worker touches so injecting an instance cannot raise inside the worker.
    """

    def __init__(self) -> None:
        """Start with one unfinished task so ``flush`` sees pending work."""
        self.unfinished_tasks = 1
        self._parked = threading.Event()

    def put_nowait(self, item) -> None:
        """Reject the record, mimicking a saturated bounded queue."""
        raise queue_mod.Full

    def get(self, *args, **kwargs):
        """Park a background worker harmlessly; it never receives an item."""
        self._parked.wait()

    def task_done(self) -> None:
        """Do nothing because this fake never dequeues an item."""


def test_emit_usage_event_swallows_sink_errors() -> None:
    """A failing telemetry sink must not propagate out of _emit_usage_event."""
    event = UsageTelemetryEvent.from_record(_one_record(), export_state="stored")
    assert _emit_usage_event(_RaisingSink(), event) is None


def test_in_memory_sink_evicts_oldest_beyond_max_events() -> None:
    """At capacity, the sink drops the oldest event and keeps the newest (FIFO)."""
    sink = InMemoryUsageTelemetrySink(max_events=1)
    record = _one_record()
    first = UsageTelemetryEvent.from_record(record, export_state="dropped")
    second = UsageTelemetryEvent.from_record(record, export_state="stored")
    sink.emit_usage(first)
    sink.emit_usage(second)
    events = sink.events()
    assert len(events) == 1
    assert events[0].attributes[_EXPORT_STATE_KEY] == "stored"


def test_in_memory_ledger_store_len_tracks_rows() -> None:
    """len(InMemoryLedgerStore) reflects the number of appended rows."""
    store = InMemoryLedgerStore()
    assert len(store) == 0
    store.append(_one_record())
    assert len(store) == 1


def test_non_blocking_store_rejects_non_positive_queue_size() -> None:
    """A non-positive queue size is rejected at construction."""
    with pytest.raises(ValueError):
        NonBlockingLedgerStore(InMemoryLedgerStore(), queue_size=0)


def test_non_blocking_store_query_delegates_to_backend() -> None:
    """query() delegates straight to the wrapped backend store."""
    store = NonBlockingLedgerStore(InMemoryLedgerStore())
    assert store.query() == []


def test_non_blocking_store_drops_record_when_queue_is_full() -> None:
    """A saturated queue drops the record and emits a 'dropped' telemetry event."""
    sink = InMemoryUsageTelemetrySink()
    store = NonBlockingLedgerStore(InMemoryLedgerStore(), telemetry_sink=sink)
    store._queue = _AlwaysFullQueue()
    store.append(_one_record())
    assert "dropped" in _export_states(sink)


def test_non_blocking_store_flush_times_out_when_writes_pending() -> None:
    """flush() returns False when work stays pending past the deadline."""
    store = NonBlockingLedgerStore(InMemoryLedgerStore())
    store._queue = _AlwaysFullQueue()
    assert store.flush(timeout=0.0) is False


def test_non_blocking_store_worker_persists_and_emits_stored() -> None:
    """An explicitly injected empty backend is preserved and receives worker writes."""
    sink = InMemoryUsageTelemetrySink()
    backend = InMemoryLedgerStore()
    ledger = _ledger(store=backend, non_blocking_store=True, telemetry_sink=sink)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=10, completion_tokens=5)
    assert ledger.flush(timeout=2.0) is True
    assert len(backend) == 1
    assert "stored" in _export_states(sink)


class _FailingStore:
    """Ledger store whose append always raises (inline-failure path)."""

    def append(self, record) -> None:
        """Always fail so the ledger records the failure as telemetry only."""
        raise RuntimeError("store down")

    def query(self, start=None, end=None):
        """Return no rows; the failing store persists nothing."""
        return []


def test_inline_store_failure_is_recorded_as_telemetry() -> None:
    """An inline store failure is swallowed, emitted, and counted, not raised."""
    sink = InMemoryUsageTelemetrySink()
    ledger = _ledger(store=_FailingStore(), telemetry_sink=sink)
    record = ledger.record_usage(
        provider="openai", model="gpt-x", prompt_tokens=1, completion_tokens=1
    )
    assert record is not None
    assert "export_error" in _export_states(sink)
    assert ledger.telemetry_health()["store_failures"] >= 1


def test_record_usage_accepts_attribution_dimensions_object() -> None:
    """record_usage accepts a pre-built AttributionDimensions without remapping."""
    record = _ledger().record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        attribution=AttributionDimensions(account="acct_one"),
    )
    assert record.attribution.account == "acct_one"


def test_attribution_from_mapping_uses_provider_alias_for_upstream_api() -> None:
    """A loose 'provider' key maps onto the upstream_api dimension."""
    dims = AttributionDimensions.from_mapping({"provider": "prov_alias"})
    assert dims.upstream_api == "prov_alias"


def test_telemetry_event_includes_optional_record_dimensions() -> None:
    """workflow_run_id and route_mode surface as event attributes when present."""
    record = _ledger().record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        workflow_run_id="wf_run_1",
        route_mode="deep",
    )
    event = UsageTelemetryEvent.from_record(record, export_state="stored")
    assert event.attributes["contextual_orchestrator.workflow_run_id"] == "wf_run_1"
    assert event.attributes["contextual_orchestrator.route_mode"] == "deep"


def test_flush_returns_true_when_store_is_synchronous() -> None:
    """CostLedger.flush short-circuits to True when the store exposes no flush()."""
    assert _ledger().flush() is True


def test_sql_ledger_store_query_builds_time_window_clauses() -> None:
    """The time-window query includes [start, end) and excludes end itself."""
    conn = sqlite3.connect(":memory:")
    try:
        store = SqlLedgerStore(conn, paramstyle="qmark")
        record = _one_record()
        store.append(record)
        assert len(store.query(start=0, end=record.created_at + 1)) == 1
        assert store.query(start=0, end=record.created_at) == []
    finally:
        conn.close()
