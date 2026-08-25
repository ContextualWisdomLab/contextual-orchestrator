"""Boundary coverage for ledger telemetry, queueing, and attribution guards.

Covers the paths ordinary happy-path ledger tests cannot reach: provider
alias mapping, telemetry ring trimming, sink export failures, queue
overflow drops, flush timeouts, background store success, idempotent
schema seeding, non-blocking wrapping, object-attribution spoof stripping,
and inline persistence failures.
"""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from contextual_orchestrator.cost_ledger import (
    ATTRIBUTION_DIMENSIONS,
    AttributionDimensions,
    CostLedger,
    InMemoryLedgerStore,
    InMemoryUsageTelemetrySink,
    NonBlockingLedgerStore,
    PriceBook,
    PriceEntry,
    SqlLedgerStore,
)
from contextual_orchestrator.kv_config import InMemoryConfigStore


def _price_book() -> PriceBook:
    book = PriceBook(InMemoryConfigStore())
    book.set_price(
        PriceEntry("openai", "gpt-x", prompt_price_per_1k=2.0, completion_price_per_1k=4.0)
    )
    return book


class _RaisingSink:
    """Telemetry sink whose exporter is broken."""

    def __init__(self) -> None:
        self.attempts = 0

    def emit_usage(self, event) -> None:
        self.attempts += 1
        raise RuntimeError("otel collector unreachable")


def test_attribution_provider_alias_maps_to_upstream_api() -> None:
    """A bare ``provider`` key aliases to ``upstream_api``; explicit wins."""
    aliased = AttributionDimensions.from_mapping({"provider": "openai"})
    assert aliased.upstream_api == "openai"

    explicit = AttributionDimensions.from_mapping(
        {"provider": "ignored-upstream", "upstream_api": "canonical"}
    )
    assert explicit.upstream_api == "canonical"

    empty = AttributionDimensions.from_mapping({"provider": ""})
    assert empty.upstream_api == "unattributed"


def test_telemetry_sink_keeps_only_the_newest_events() -> None:
    """The in-memory sink is a bounded ring, not an unbounded list."""
    from contextual_orchestrator.cost_ledger import UsageTelemetryEvent

    sink = InMemoryUsageTelemetrySink(max_events=2)
    for index in range(4):
        sink.emit_usage(
            UsageTelemetryEvent(name="e", attributes={}, metrics={}, status="ok")
        )
        time.sleep(0)
    retained = sink.events()
    assert len(retained) == 2


def _working_ledger_with_broken_sink() -> tuple[CostLedger, _RaisingSink]:
    sink = _RaisingSink()
    store = InMemoryLedgerStore()
    ledger = CostLedger(_price_book(), store=store, telemetry_sink=sink)
    return ledger, sink


def test_inline_store_failure_is_health_only_and_never_raises() -> None:
    """A persisting store failure must not fail the completion request."""
    class _ExplodingStore:
        def append(self, record) -> None:
            raise ConnectionError("ledger database unreachable")

        def query(self, start=None, end=None):
            return []

    sink = InMemoryUsageTelemetrySink()
    ledger = CostLedger(_price_book(), store=_ExplodingStore(), telemetry_sink=sink)

    record = ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=3,
                                 completion_tokens=2)

    health = ledger.telemetry_health()
    assert health["records_accepted"] == 1
    assert health["store_failures"] == 1
    assert health["last_error_type"] == "ConnectionError"
    assert health["records_stored"] == 0
    states = {
        event.attributes["contextual_orchestrator.usage.export_state"]
        for event in sink.events()
    }
    assert states == {"export_error"}
    # The record is still returned so the caller keeps its accounting data.
    assert record.total_tokens == 5

    # A plain store has neither flush nor telemetry_health: both degrade.
    assert ledger.flush() is True
    plain = CostLedger(_price_book(), store=InMemoryLedgerStore())
    assert plain.flush(timeout=None) is True
    base_health = plain.telemetry_health()
    assert base_health["store_failures"] == 0


def test_broken_telemetry_export_never_affects_completions() -> None:
    """Sink explosions are swallowed on every emission path."""
    ledger, sink = _working_ledger_with_broken_sink()
    record = ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1,
                                 completion_tokens=1)
    assert ledger.store.query()[0]["usage_record_id"] == record.usage_record_id
    assert sink.attempts >= 1  # the failure happened and was contained

    wrapped = CostLedger(
        _price_book(),
        store=InMemoryLedgerStore(),
        telemetry_sink=_RaisingSink(),
        non_blocking_store=True,
        store_queue_size=1,
    )
    wrapped.record_usage(provider="openai", model="gpt-x", prompt_tokens=1,
                         completion_tokens=1)
    assert wrapped.flush(timeout=5.0) is True
    assert len(wrapped.records()) == 1
    # Health merges the wrapper counters; a clean run has no error type.
    health = wrapped.telemetry_health()
    assert health["records_stored"] == 1
    assert health["last_error_type"] is None


def test_queue_size_must_be_positive() -> None:
    """A zero-capacity queue is a configuration error, not a silent drop-all."""
    with pytest.raises(ValueError, match="queue_size must be at least 1"):
        NonBlockingLedgerStore(InMemoryLedgerStore(), queue_size=0)


class _GatedBackend:
    """Backend whose first append blocks until the test releases it."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.gate = threading.Event()
        self.appended: list[str] = []

    def append(self, record) -> None:
        self.appended.append(record.usage_record_id)
        if not self.gate.is_set():
            self.entered.set()
            assert self.gate.wait(timeout=10)

    def query(self, start=None, end=None):
        return []


def test_queue_overflow_drops_records_with_telemetry_evidence() -> None:
    """When the queue saturates, records drop loudly instead of blocking I/O."""
    backend = _GatedBackend()
    sink = InMemoryUsageTelemetrySink(max_events=64)
    store = NonBlockingLedgerStore(backend, queue_size=1, telemetry_sink=sink)

    first = None
    try:
        from contextual_orchestrator.cost_ledger import UsageRecord, UNATTRIBUTED

        def make_record(index: int) -> UsageRecord:
            return UsageRecord(
                usage_record_id=f"usage_{index}",
                created_at=int(time.time()),
                workflow_run_id=None,
                request_channel="sync",
                route_mode=None,
                provider_name="openai",
                model_name="gpt-x",
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                cost_amount=0.0,
                currency_code="USD",
                attribution=AttributionDimensions(),
            )

        store.append(make_record(1))
        assert backend.entered.wait(timeout=10)  # worker blocked inside append
        store.append(make_record(2))  # fills the free slot
        third = make_record(3)
        store.append(third)  # queue.Full -> dropped path
        first = third
    finally:
        backend.gate.set()

    assert store.flush(timeout=10.0) is True
    health = store.telemetry_health()
    assert health["records_accepted"] == 2
    assert health["records_dropped"] == 1
    assert health["records_stored"] == 2
    assert health["last_error_type"] == "queue.Full"
    dropped_states = {
        event.attributes["contextual_orchestrator.usage.export_state"]
        for event in sink.events()
    }
    assert {"queued", "dropped", "stored"} <= dropped_states
    del first


def test_flush_timeout_returns_false_while_worker_is_stuck() -> None:
    """flush(timeout) reports False rather than hanging past its deadline."""
    backend = _GatedBackend()
    store = NonBlockingLedgerStore(backend, queue_size=4)

    from contextual_orchestrator.cost_ledger import UsageRecord

    store.append(
        UsageRecord(
            usage_record_id="usage_stuck",
            created_at=int(time.time()),
            workflow_run_id=None,
            request_channel="sync",
            route_mode=None,
            provider_name="openai",
            model_name="gpt-x",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            cost_amount=0.0,
            currency_code="USD",
            attribution=AttributionDimensions(),
        )
    )
    assert backend.entered.wait(timeout=10)
    try:
        started = time.monotonic()
        assert store.flush(timeout=0.05) is False
        assert time.monotonic() - started < 5.0
    finally:
        backend.gate.set()
    assert store.flush(timeout=10.0) is True


def test_corrupt_price_component_text_is_rejected_not_parsed() -> None:
    """A garbage price string yields no entry rather than a crash or zero."""
    from contextual_orchestrator.cost_ledger import _PRICE_CATEGORY, _price_key

    config = InMemoryConfigStore()
    config.set(
        _PRICE_CATEGORY,
        _price_key("openai", "corrupt-model"),
        {
            "prompt_price_per_1k": "not-a-number",
            "completion_price_per_1k": 2.0,
            "currency_code": "USD",
        },
    )
    book = PriceBook(config)
    assert book.get_price("openai", "corrupt-model") is None
    cost, currency = book.compute_cost("openai", "corrupt-model", 1000, 1000)
    assert cost == 0.0
    assert currency == "USD"


def test_working_background_store_marks_records_stored() -> None:
    """The worker success path stores rows and emits 'stored' telemetry."""
    sink = InMemoryUsageTelemetrySink(max_events=16)
    backend = InMemoryLedgerStore()
    store = NonBlockingLedgerStore(backend, queue_size=4, telemetry_sink=sink)

    from contextual_orchestrator.cost_ledger import UsageRecord

    store.append(
        UsageRecord(
            usage_record_id="usage_ok",
            created_at=int(time.time()),
            workflow_run_id="workflow_run_42",
            request_channel="sync",
            route_mode="cost_aware",
            provider_name="openai",
            model_name="gpt-x",
            prompt_tokens=7,
            completion_tokens=3,
            total_tokens=10,
            cost_amount=0.02,
            currency_code="USD",
            attribution=AttributionDimensions(),
        )
    )
    assert store.flush(timeout=10.0) is True
    assert len(backend) == 1
    health = store.telemetry_health()
    assert health["records_stored"] == 1
    assert health["records_accepted"] == 1
    states = {
        event.attributes["contextual_orchestrator.usage.export_state"]
        for event in sink.events()
    }
    assert states == {"queued", "stored"}
    workflow_event = next(
        event
        for event in sink.events()
        if event.attributes.get("contextual_orchestrator.workflow_run_id")
    )
    assert (
        workflow_event.attributes["contextual_orchestrator.workflow_run_id"]
        == "workflow_run_42"
    )
    assert workflow_event.attributes["contextual_orchestrator.route_mode"] == (
        "cost_aware"
    )


def test_sql_dimension_seeding_is_idempotent_on_existing_rows() -> None:
    """Re-opening the schema skips inserts when catalog rows already exist."""
    connection = sqlite3.connect(":memory:")
    SqlLedgerStore(connection, paramstyle="qmark")
    SqlLedgerStore(connection, paramstyle="qmark")  # second pass hits exists-branch

    cur = connection.cursor()
    cur.execute("SELECT dimension_name FROM cost_attribution_dimensions")
    names = [row[0] for row in cur.fetchall()]
    assert sorted(names) == sorted(ATTRIBUTION_DIMENSIONS)
    assert len(names) == len(set(names))


def test_non_blocking_wrapper_persists_through_background_worker() -> None:
    """non_blocking_store=True wraps the store and still lands every row."""
    sink = InMemoryUsageTelemetrySink(max_events=16)
    ledger = CostLedger(
        _price_book(),
        store=InMemoryLedgerStore(),
        telemetry_sink=sink,
        non_blocking_store=True,
        store_queue_size=8,
    )
    assert isinstance(ledger.store, NonBlockingLedgerStore)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=10,
                        completion_tokens=5)
    assert ledger.flush(timeout=10.0) is True
    rows = ledger.records()
    assert len(rows) == 1
    assert rows[0]["cost_amount"] == pytest.approx(0.04)


def test_object_attribution_cannot_spoof_execution_identity() -> None:
    """Dataclass attributions force upstream/model identity from the call."""
    ledger = CostLedger(_price_book())
    dims = AttributionDimensions(
        account="acme_corp",
        service="billing_service",
        upstream_api="spoofed-provider",
        model_name="spoofed-model",
        team="platform_team",
        group="growth_group",
        company="acme_company",
    )
    record = ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        attribution=dims,
    )
    assert record.attribution.account == "acme_corp"
    assert record.attribution.team == "platform_team"
    assert record.attribution.upstream_api == "openai"
    assert record.attribution.model_name == "gpt-x"

    # With a blank provider/model the forced-unattributed identity survives.
    blank = ledger.record_usage(
        provider="",
        model="",
        prompt_tokens=1,
        completion_tokens=1,
        attribution=dims,
    )
    assert blank.attribution.upstream_api == "unattributed"
    assert blank.attribution.model_name == "unattributed"


def test_dict_attribution_spoof_keys_are_stripped_then_blank_identity_wins() -> None:
    """Caller-supplied model/provider keys never survive; blanks stay unattributed."""
    ledger = CostLedger(_price_book())
    record = ledger.record_usage(
        provider="",
        model="",
        prompt_tokens=1,
        completion_tokens=1,
        attribution={
            "model_name": "spoofed-model",
            "provider": "spoofed-provider",
            "upstream_api": "also-spoofed",
            "team": "honest_team",
        },
    )
    assert record.attribution.model_name == "unattributed"
    assert record.attribution.upstream_api == "unattributed"
    assert record.attribution.team == "honest_team"

    honest = ledger.record_usage(
        provider="anthropic",
        model="claude-y",
        prompt_tokens=1,
        completion_tokens=1,
        attribution={"model_name": "spoofed-model"},
    )
    assert honest.attribution.model_name == "claude-y"
    assert honest.attribution.upstream_api == "anthropic"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
