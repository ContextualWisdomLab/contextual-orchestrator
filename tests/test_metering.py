"""Canonical usage export integration tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

from contextual_orchestrator.cost_ledger import (
    CostLedger,
    InMemoryLedgerStore,
    InMemoryUsageTelemetrySink,
    NonBlockingLedgerStore,
    PriceBook,
    PriceEntry,
    SqlLedgerStore,
    UsageRecord,
)
from contextual_orchestrator.metering import CanonicalUsageRecordSink
from contextual_orchestrator.kv_config import InMemoryConfigStore


class _RecordingUsageSink:
    """Collect exported record ids for ledger acceptance assertions."""

    def __init__(self) -> None:
        self.ids: list[str] = []

    def emit_usage_record(self, record: UsageRecord) -> None:
        self.ids.append(record.usage_record_id)


def test_record_sink_builds_and_enqueues_without_content() -> None:
    """The sink forwards only the prompt-safe ledger mapping to the builder."""
    built: list[dict[str, object]] = []
    queued: list[dict[str, object]] = []

    def builder(record: dict[str, object], **identity: str | None) -> dict[str, object]:
        event = {"record": record, "identity": identity}
        built.append(event)
        return event

    sink = CanonicalUsageRecordSink(
        event_builder=builder,
        enqueue=queued.append,
        identity={"tenant_reference": "urn:cwl:tenant:test"},
    )
    record = UsageRecord(
        usage_record_id="usage_export_test",
        created_at=1,
        workflow_run_id="run-1",
        request_channel="sync",
        route_mode="route",
        provider_name="openai",
        model_name="gpt-x",
        prompt_tokens=2,
        completion_tokens=3,
        total_tokens=5,
        cost_amount=0.01,
        currency_code="USD",
    )

    sink.emit_usage_record(record)

    assert queued == built
    assert "prompt" not in queued[0]
    assert "cost_amount" not in queued[0]["record"]
    assert "currency_code" not in queued[0]["record"]
    assert queued[0]["identity"] == {"tenant_reference": "urn:cwl:tenant:test"}


def test_record_sink_rejects_noncanonical_identity_before_builder() -> None:
    """Private content cannot enter the canonical builder through identity."""
    built = False

    def builder(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal built
        built = True
        return {}

    try:
        CanonicalUsageRecordSink(
            event_builder=builder,
            enqueue=lambda _event: None,
            identity={"prompt": "must-not-reach-builder"},
        )
    except ValueError as error:
        assert "prompt" in str(error)
    else:
        raise AssertionError("noncanonical identity was accepted")
    assert built is False


def test_cost_ledger_reports_sink_failure_without_failing_completion() -> None:
    """A broken billing export is observable while the existing ledger survives."""
    telemetry = InMemoryUsageTelemetrySink()

    def builder(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("export unavailable")

    sink = CanonicalUsageRecordSink(
        event_builder=builder,
        enqueue=lambda _event: None,
        identity={},
    )
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(price_book, telemetry_sink=telemetry, usage_sink=sink)

    record = ledger.record_usage(
        provider="openai", model="gpt-x", prompt_tokens=1, completion_tokens=1
    )

    assert record.usage_record_id.startswith("usage_")
    assert telemetry.events()[-1].error_type == "RuntimeError"
    health = ledger.telemetry_health()
    assert health["export_failures"] == 1
    assert health["last_error_type"] == "RuntimeError"


def test_billing_export_requires_store_acceptance() -> None:
    """A dropped local record must not become a billing-only record."""

    class _RejectingStore:
        def append(self, _record: UsageRecord) -> bool:
            return False

        def query(self, _start: int | None = None, _end: int | None = None) -> list[dict[str, object]]:
            return []

    exported: list[dict[str, object]] = []
    sink = CanonicalUsageRecordSink(
        event_builder=lambda record, **_identity: {"record": record},
        enqueue=exported.append,
        identity={},
    )
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(price_book, store=_RejectingStore(), usage_sink=sink)

    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1, completion_tokens=1)

    assert exported == []


def test_duplicate_usage_record_is_not_counted_or_exported_twice() -> None:
    """Idempotent local writes must stay idempotent at the billing boundary."""
    exported: list[dict[str, object]] = []
    telemetry = InMemoryUsageTelemetrySink()
    sink = CanonicalUsageRecordSink(
        event_builder=lambda record, **_identity: {"record": record},
        enqueue=exported.append,
        identity={},
    )
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(price_book, telemetry_sink=telemetry, usage_sink=sink)

    for _ in range(2):
        ledger.record_usage(
            provider="openai",
            model="gpt-x",
            prompt_tokens=1,
            completion_tokens=1,
            usage_record_id="usage_duplicate",
        )

    assert len(exported) == 1
    assert ledger.telemetry_health()["records_stored"] == 1
    assert ledger.telemetry_health()["records_dropped"] == 1
    assert telemetry.events()[-1].error_type == "duplicate"


def test_billing_export_waits_for_caller_owned_sqlite_commit() -> None:
    """A rolled-back caller transaction must not leave a billing-only event."""
    connection = sqlite3.connect(":memory:")
    store = SqlLedgerStore(connection, paramstyle="qmark")
    sink = _RecordingUsageSink()
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(price_book, store=store, usage_sink=sink)

    connection.execute("BEGIN")
    ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        usage_record_id="usage_rolled_back",
    )

    assert sink.ids == []
    connection.rollback()
    assert ledger.flush() is True
    assert ledger.telemetry_health()["records_stored"] == 0
    assert ledger.telemetry_health()["records_dropped"] == 1
    assert store.query() == []

    connection.execute("BEGIN")
    ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        usage_record_id="usage_committed",
    )
    assert sink.ids == []
    connection.commit()

    assert ledger.flush() is True
    assert sink.ids == ["usage_committed"]


def test_billing_export_flush_uses_record_id_lookup() -> None:
    """Deferred billing release must not scan the complete SQL ledger."""
    connection = sqlite3.connect(":memory:")
    store = SqlLedgerStore(connection, paramstyle="qmark")
    sink = _RecordingUsageSink()
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(price_book, store=store, usage_sink=sink)
    statements: list[str] = []
    connection.set_trace_callback(statements.append)

    connection.execute("BEGIN")
    ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        usage_record_id="usage_targeted_lookup",
    )
    connection.commit()

    assert ledger.flush() is True
    assert sink.ids == ["usage_targeted_lookup"]
    assert not any("SELECT u.usage_record_id" in statement for statement in statements)
    assert any(
        "SELECT usage_record_id FROM llm_usage_records WHERE usage_record_id IN" in statement
        for statement in statements
    )


def test_deferred_export_lookup_failure_does_not_fail_current_record() -> None:
    """A deferred-store read failure must not block a later usage write."""
    connection = sqlite3.connect(":memory:")
    store = SqlLedgerStore(connection, paramstyle="qmark")
    sink = _RecordingUsageSink()
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(price_book, store=store, usage_sink=sink)

    connection.execute("BEGIN")
    ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        usage_record_id="usage_deferred_read",
    )
    connection.commit()
    original_lookup = store.existing_usage_record_ids

    def fail_lookup(_usage_record_ids: list[str]) -> set[str]:
        raise RuntimeError("temporary read failure")

    store.existing_usage_record_ids = fail_lookup  # type: ignore[method-assign]
    current = ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        usage_record_id="usage_current_write",
    )

    assert current.usage_record_id == "usage_current_write"
    assert sink.ids == ["usage_current_write"]
    assert ledger.telemetry_health()["store_failures"] == 1

    store.existing_usage_record_ids = original_lookup  # type: ignore[method-assign]
    assert ledger.flush() is True
    assert sink.ids == ["usage_current_write", "usage_deferred_read"]


def test_async_billing_export_preserves_caller_owned_sqlite_transaction() -> None:
    """A caller transaction persists before export and never bills a rollback."""
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    store = SqlLedgerStore(connection, paramstyle="qmark")
    sink = _RecordingUsageSink()
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(
        price_book,
        store=store,
        non_blocking_store=True,
        usage_sink=sink,
    )

    connection.execute("BEGIN")
    ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        usage_record_id="usage_async_rolled_back",
    )
    assert store.query()[0]["usage_record_id"] == "usage_async_rolled_back"
    connection.rollback()
    assert ledger.flush(timeout=5) is True
    assert sink.ids == []
    assert store.query() == []
    assert ledger.telemetry_health()["records_dropped"] == 1

    connection.execute("BEGIN")
    ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        usage_record_id="usage_async_committed",
    )
    assert sink.ids == []
    connection.commit()
    assert ledger.flush(timeout=5) is True
    assert sink.ids == ["usage_async_committed"]
    assert ledger.telemetry_health()["records_stored"] == 1


def test_async_open_transaction_duplicate_is_reported_as_dropped() -> None:
    """A duplicate in the synchronous caller-transaction path remains observable."""
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    store = SqlLedgerStore(connection, paramstyle="qmark")
    telemetry = InMemoryUsageTelemetrySink()
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(
        price_book,
        store=store,
        non_blocking_store=True,
        telemetry_sink=telemetry,
        usage_sink=_RecordingUsageSink(),
    )

    connection.execute("BEGIN")
    for _ in range(2):
        ledger.record_usage(
            provider="openai",
            model="gpt-x",
            prompt_tokens=1,
            completion_tokens=1,
            usage_record_id="usage_open_transaction_duplicate",
        )

    assert ledger.telemetry_health()["records_dropped"] == 1
    assert telemetry.events()[-1].error_type == "duplicate"
    connection.rollback()


def test_non_blocking_store_preserves_transaction_without_billing_sink() -> None:
    """A caller transaction is never handed to the background worker."""
    connection = sqlite3.connect(":memory:")
    store = SqlLedgerStore(connection, paramstyle="qmark")
    wrapper = NonBlockingLedgerStore(store)
    record = UsageRecord(
        usage_record_id="usage_async_without_sink",
        created_at=1,
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
    )

    connection.execute("BEGIN")
    assert wrapper.append(record)
    assert wrapper.flush(timeout=5)
    assert store.query()[0]["usage_record_id"] == record.usage_record_id
    connection.rollback()
    assert store.query() == []


def test_async_billing_export_does_not_race_new_transaction() -> None:
    """A transaction opened after enqueue must defer export until it settles."""
    class _RaceBackend:
        def __init__(self) -> None:
            self.append_started = threading.Event()
            self.release_append = threading.Event()
            self.open_transaction = False
            self.rows: list[UsageRecord] = []
            self.pending: list[UsageRecord] = []

        def append(self, record: UsageRecord) -> bool:
            self.append_started.set()
            assert self.release_append.wait(timeout=5)
            (self.pending if self.open_transaction else self.rows).append(record)
            return True

        def has_open_transaction(self) -> bool:
            return self.open_transaction

        def existing_usage_record_ids(self, usage_record_ids: list[str]) -> set[str]:
            return {
                record.usage_record_id
                for record in self.rows
                if record.usage_record_id in usage_record_ids
            }

        def query(self, start=None, end=None):
            del start, end
            return [record.as_dict() for record in self.rows]

        def rollback(self) -> None:
            self.pending.clear()
            self.open_transaction = False

    backend = _RaceBackend()
    sink = _RecordingUsageSink()
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(
        price_book,
        store=backend,
        non_blocking_store=True,
        usage_sink=sink,
    )

    ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        usage_record_id="usage_async_raced_rollback",
    )
    assert backend.append_started.wait(timeout=5)
    backend.open_transaction = True
    backend.release_append.set()
    assert ledger.flush(timeout=5) is True
    backend.rollback()
    assert ledger.flush(timeout=5) is True
    assert sink.ids == []


def test_inline_health_counts_concurrent_export_failures() -> None:
    """Concurrent request threads must not lose export-failure increments."""
    telemetry = InMemoryUsageTelemetrySink()

    class _FailingExportSink:
        def emit_usage_record(self, _record: UsageRecord) -> None:
            raise RuntimeError("export unavailable")

    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(
        price_book,
        telemetry_sink=telemetry,
        usage_sink=_FailingExportSink(),
    )
    count = 32

    with ThreadPoolExecutor(max_workers=count) as executor:
        list(
            executor.map(
                lambda _index: ledger.record_usage(
                    provider="openai",
                    model="gpt-x",
                    prompt_tokens=1,
                    completion_tokens=1,
                ),
                range(count),
            )
        )

    assert ledger.telemetry_health()["export_failures"] == count


def test_billing_export_skips_non_blocking_queue_drops() -> None:
    """A queue.Full drop must not become a billing-only record."""
    entered = threading.Event()
    release = threading.Event()

    class _BlockingStore:
        def append(self, record: UsageRecord) -> bool:
            del record
            entered.set()
            assert release.wait(timeout=5)
            return True

        def query(self, start=None, end=None):
            del start, end
            return []

    sink = _RecordingUsageSink()
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    store = NonBlockingLedgerStore(_BlockingStore(), queue_size=1)
    ledger = CostLedger(price_book, store=store, usage_sink=sink)
    try:
        ledger.record_usage(
            provider="openai",
            model="gpt-x",
            prompt_tokens=1,
            completion_tokens=1,
            usage_record_id="usage_1",
        )
        assert entered.wait(timeout=5)
        ledger.record_usage(
            provider="openai",
            model="gpt-x",
            prompt_tokens=1,
            completion_tokens=1,
            usage_record_id="usage_2",
        )
        ledger.record_usage(
            provider="openai",
            model="gpt-x",
            prompt_tokens=1,
            completion_tokens=1,
            usage_record_id="usage_3",
        )
    finally:
        release.set()
        assert store.flush(timeout=5)
    assert sink.ids == ["usage_1", "usage_2"]


def test_non_blocking_billing_export_waits_for_backend_success() -> None:
    """A background persistence failure must not create a billing event."""

    class _FailingBackend:
        def append(self, _record: UsageRecord) -> bool:
            raise RuntimeError("backend unavailable")

        def query(self, start=None, end=None):
            del start, end
            return []

    sink = _RecordingUsageSink()
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(
        price_book,
        store=_FailingBackend(),
        non_blocking_store=True,
        usage_sink=sink,
    )

    ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        usage_record_id="usage_backend_failure",
    )

    assert ledger.flush(timeout=5)
    assert sink.ids == []


def test_non_blocking_billing_export_deduplicates_backend_writes() -> None:
    """A backend duplicate must not be exported as a second billing event."""
    sink = _RecordingUsageSink()
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(
        price_book,
        store=InMemoryLedgerStore(),
        non_blocking_store=True,
        usage_sink=sink,
    )

    for _ in range(2):
        ledger.record_usage(
            provider="openai",
            model="gpt-x",
            prompt_tokens=1,
            completion_tokens=1,
            usage_record_id="usage_async_duplicate",
        )

    assert ledger.flush(timeout=5)
    assert sink.ids == ["usage_async_duplicate"]
    assert ledger.telemetry_health()["records_dropped"] == 1


def test_non_blocking_billing_export_failure_updates_health() -> None:
    """A post-persistence billing failure remains visible without failing work."""

    class _FailingExportSink:
        def emit_usage_record(self, _record: UsageRecord) -> None:
            raise RuntimeError("export unavailable")

    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 1.0, 1.0))
    ledger = CostLedger(
        price_book,
        store=InMemoryLedgerStore(),
        non_blocking_store=True,
        usage_sink=_FailingExportSink(),
    )

    ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=1,
        completion_tokens=1,
        usage_record_id="usage_async_export_failure",
    )

    assert ledger.flush(timeout=5)
    health = ledger.telemetry_health()
    assert health["records_stored"] == 1
    assert health["export_failures"] == 1
    assert health["last_error_type"] == "RuntimeError"
