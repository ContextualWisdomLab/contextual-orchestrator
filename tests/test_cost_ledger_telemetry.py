"""Telemetry, non-blocking, and inline-failure branches of the cost ledger.

Covers the best-effort telemetry emit + buffer eviction, the queue-full drop
and flush-timeout paths, the non-blocking worker store path, inline
store-failure handling, the in-memory store length, and the SQL time-window
WHERE clauses — all on stdlib fakes, no Postgres.
"""

from __future__ import annotations

from pathlib import Path
import queue as queue_mod
import sqlite3
import sys

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
    return [
        event.attributes.get("contextual_orchestrator.usage.export_state")
        for event in sink.events()
    ]


class _RaisingSink:
    """Telemetry sink whose emit always raises, proving emit is best-effort."""

    def emit_usage(self, event) -> None:
        """Always fail, so callers must swallow the error."""
        raise RuntimeError("telemetry backend down")


class _AlwaysFullQueue:
    """Fake queue that rejects every put and never drains (drop/timeout paths)."""

    unfinished_tasks = 1

    def put_nowait(self, item) -> None:
        """Reject the record, mimicking a saturated bounded queue."""
        raise queue_mod.Full


# --- best-effort telemetry emit + buffer eviction ---------------------------


def test_emit_usage_event_swallows_sink_errors() -> None:
    event = UsageTelemetryEvent.from_record(_one_record(), export_state="stored")
    assert _emit_usage_event(_RaisingSink(), event) is None


def test_in_memory_sink_evicts_oldest_beyond_max_events() -> None:
    sink = InMemoryUsageTelemetrySink(max_events=1)
    event = UsageTelemetryEvent.from_record(_one_record(), export_state="stored")
    sink.emit_usage(event)
    sink.emit_usage(event)
    assert len(sink.events()) == 1


# --- in-memory ledger store -------------------------------------------------


def test_in_memory_ledger_store_len_tracks_rows() -> None:
    store = InMemoryLedgerStore()
    assert len(store) == 0
    store.append(_one_record())
    assert len(store) == 1


# --- non-blocking store: validation, drop, query, flush, worker -------------


def test_non_blocking_store_rejects_non_positive_queue_size() -> None:
    with pytest.raises(ValueError):
        NonBlockingLedgerStore(InMemoryLedgerStore(), queue_size=0)


def test_non_blocking_store_query_delegates_to_backend() -> None:
    store = NonBlockingLedgerStore(InMemoryLedgerStore())
    assert store.query() == []


def test_non_blocking_store_drops_record_when_queue_is_full() -> None:
    sink = InMemoryUsageTelemetrySink()
    store = NonBlockingLedgerStore(InMemoryLedgerStore(), telemetry_sink=sink)
    store._queue = _AlwaysFullQueue()
    store.append(_one_record())
    assert "dropped" in _export_states(sink)


def test_non_blocking_store_flush_times_out_when_writes_pending() -> None:
    store = NonBlockingLedgerStore(InMemoryLedgerStore())
    store._queue = _AlwaysFullQueue()
    assert store.flush(timeout=0.0) is False


def test_non_blocking_store_worker_persists_and_emits_stored() -> None:
    sink = InMemoryUsageTelemetrySink()
    ledger = _ledger(non_blocking_store=True, telemetry_sink=sink)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=10, completion_tokens=5)
    assert ledger.flush(timeout=2.0) is True
    assert "stored" in _export_states(sink)


# --- inline store failure ---------------------------------------------------


class _FailingStore:
    """Ledger store whose append always raises (inline-failure path)."""

    def append(self, record) -> None:
        """Always fail so the ledger records the failure as telemetry only."""
        raise RuntimeError("store down")

    def query(self, start=None, end=None):
        """Return no rows; the failing store persists nothing."""
        return []


def test_inline_store_failure_is_recorded_as_telemetry() -> None:
    sink = InMemoryUsageTelemetrySink()
    ledger = _ledger(store=_FailingStore(), telemetry_sink=sink)
    record = ledger.record_usage(
        provider="openai", model="gpt-x", prompt_tokens=1, completion_tokens=1
    )
    assert record is not None
    assert "export_error" in _export_states(sink)
    assert ledger.telemetry_health()["store_failures"] >= 1


# --- attribution passed as a dimensions object ------------------------------


def test_record_usage_accepts_attribution_dimensions_object() -> None:
    record = _ledger().record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        attribution=AttributionDimensions(account="acct_one"),
    )
    assert record.attribution.account == "acct_one"


def test_attribution_from_mapping_uses_provider_alias_for_upstream_api() -> None:
    dims = AttributionDimensions.from_mapping({"provider": "prov_alias"})
    assert dims.upstream_api == "prov_alias"


# --- telemetry event carries optional record dimensions ---------------------


def test_telemetry_event_includes_optional_record_dimensions() -> None:
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
    # inline InMemoryLedgerStore exposes no flush(); CostLedger.flush short-circuits
    assert _ledger().flush() is True


# --- SQL ledger store time-window WHERE clauses -----------------------------


def test_sql_ledger_store_query_builds_time_window_clauses() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        store = SqlLedgerStore(conn, paramstyle="qmark")
        record = _one_record()
        store.append(record)
        rows = store.query(start=0, end=record.created_at + 1)
        assert isinstance(rows, list)
        assert len(rows) == 1
    finally:
        conn.close()
