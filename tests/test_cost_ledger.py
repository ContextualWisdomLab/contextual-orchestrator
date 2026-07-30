"""Cost ledger: price computation, per-request writes, multi-dimensional rollup."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.cost_ledger import (  # noqa: E402
    ATTRIBUTION_DIMENSIONS,
    AttributionDimensions,
    CostLedger,
    InMemoryLedgerStore,
    InMemoryUsageTelemetrySink,
    NonBlockingLedgerStore,
    PriceBook,
    PriceEntry,
    SqlLedgerStore,
    UsageRecord,
    UsageTelemetryEvent,
    dimension_catalog,
)
from contextual_orchestrator.conventions import is_two_word_snake_case  # noqa: E402
from contextual_orchestrator.kv_config import InMemoryConfigStore  # noqa: E402


def _priced_ledger(store=None, **kwargs) -> CostLedger:
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("openai", "gpt-x", prompt_price_per_1k=2.0, completion_price_per_1k=4.0))
    price_book.set_price(PriceEntry("anthropic", "claude-y", prompt_price_per_1k=3.0, completion_price_per_1k=6.0))
    return CostLedger(price_book, store=store, **kwargs)


class _FailingLedgerStore:
    def append(self, record) -> None:
        raise RuntimeError("P2028 Transaction API error with secret prompt and secret answer")

    def query(self, start=None, end=None):
        return []


def test_price_computation_uses_per_1k_rates() -> None:
    ledger = _priced_ledger()
    # 1000 prompt * $2/1k + 500 completion * $4/1k = 2.0 + 2.0 = 4.0
    record = ledger.record_usage(
        provider="openai", model="gpt-x", prompt_tokens=1000, completion_tokens=500
    )
    assert record.cost_amount == 4.0
    assert record.currency_code == "USD"
    assert record.total_tokens == 1500


def test_unpriced_model_costs_zero_and_still_records() -> None:
    ledger = _priced_ledger()
    record = ledger.record_usage(
        provider="mystery", model="unpriced", prompt_tokens=100, completion_tokens=50
    )
    assert record.cost_amount == 0.0
    assert len(ledger.records()) == 1


def test_provider_wildcard_price_entry() -> None:
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("openai", "*", prompt_price_per_1k=1.0, completion_price_per_1k=1.0))
    ledger = CostLedger(price_book)
    record = ledger.record_usage(provider="openai", model="any-model", prompt_tokens=1000, completion_tokens=1000)
    assert record.cost_amount == 2.0


def test_writes_carry_full_attribution() -> None:
    ledger = _priced_ledger()
    record = ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=10,
        completion_tokens=10,
        attribution={
            "account": "acct-1",
            "service": "search",
            "team": "alpha",
            "group": "platform",
            "company": "acme",
        },
    )
    row = record.as_dict()
    assert row["account_name"] == "acct-1"
    assert row["service_name"] == "search"
    assert row["team_name"] == "alpha"
    assert row["group_name"] == "platform"
    assert row["company_name"] == "acme"
    # upstream_api + model_name default to the served provider/model
    assert row["upstream_api"] == "openai"
    assert row["model_name"] == "gpt-x"


def test_usage_telemetry_event_is_prompt_and_answer_safe() -> None:
    sink = InMemoryUsageTelemetrySink()
    ledger = _priced_ledger(telemetry_sink=sink)

    ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=10,
        completion_tokens=5,
        attribution={"team": "alpha", "company": "acme"},
        workflow_run_id="run_123",
    )

    event = sink.events()[-1]
    assert event.name == "gen_ai.client.usage"
    assert event.metrics["gen_ai.usage.input_tokens"] == 10.0
    assert event.attributes["contextual_orchestrator.attribution.team"] == "alpha"
    assert "prompt_text" not in event.attributes
    assert "answer" not in event.attributes
    assert all("prompt" not in key for key in event.attributes)
    assert all("answer" not in key for key in event.attributes)


def test_non_blocking_store_records_p2028_like_failure_as_telemetry_only() -> None:
    sink = InMemoryUsageTelemetrySink()
    ledger = _priced_ledger(
        store=NonBlockingLedgerStore(
            _FailingLedgerStore(),
            queue_size=4,
            telemetry_sink=sink,
        )
    )

    record = ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=10,
        completion_tokens=5,
    )
    assert record.usage_record_id.startswith("usage_")
    assert ledger.flush(timeout=1.0)

    health = ledger.telemetry_health()
    assert health["store_failures"] == 1
    assert health["records_stored"] == 0
    export_states = {
        event.attributes["contextual_orchestrator.usage.export_state"]
        for event in sink.events()
    }
    assert {"queued", "export_error"} <= export_states
    # Only the exception type is exported; DB/client messages can contain
    # deployment-specific text and must not become telemetry payload.
    assert "P2028" not in repr(sink.events())
    assert "secret prompt" not in repr(sink.events())
    assert "secret answer" not in repr(sink.events())


def test_multi_dimensional_rollup_correctness() -> None:
    ledger = _priced_ledger()
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1000, completion_tokens=1000,
                        attribution={"team": "alpha", "company": "acme"})  # 2 + 4 = 6
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1000, completion_tokens=0,
                        attribution={"team": "beta", "company": "acme"})  # 2
    ledger.record_usage(provider="anthropic", model="claude-y", prompt_tokens=1000, completion_tokens=1000,
                        attribution={"team": "alpha", "company": "globex"})  # 3 + 6 = 9

    by_team = ledger.rollup("team")
    assert by_team["alpha"]["cost_amount"] == 15.0
    assert by_team["alpha"]["record_count"] == 2
    assert by_team["beta"]["cost_amount"] == 2.0

    by_company = ledger.rollup("company")
    assert by_company["acme"]["cost_amount"] == 8.0
    assert by_company["globex"]["cost_amount"] == 9.0

    by_provider = ledger.rollup("provider")  # alias for upstream_api
    assert by_provider["openai"]["cost_amount"] == 8.0
    assert by_provider["anthropic"]["cost_amount"] == 9.0

    by_model = ledger.rollup("model_name")
    assert by_model["gpt-x"]["cost_amount"] == 8.0

    # grand total across everything
    assert ledger.total()["cost_amount"] == 17.0


def test_rollup_by_every_declared_dimension_is_supported() -> None:
    ledger = _priced_ledger()
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=100, completion_tokens=100,
                        attribution={name: f"{name}-value" for name in ATTRIBUTION_DIMENSIONS})
    for dimension in ATTRIBUTION_DIMENSIONS:
        buckets = ledger.rollup(dimension)
        assert len(buckets) == 1


def test_rollup_rejects_unknown_dimension() -> None:
    ledger = _priced_ledger()
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1, completion_tokens=1)
    try:
        ledger.rollup("nonsense_dimension")
    except ValueError as exc:
        assert "unknown attribution dimension" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for unknown dimension")


def test_time_window_filters_records() -> None:
    ledger = _priced_ledger()
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1000, completion_tokens=0, created_at=100)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1000, completion_tokens=0, created_at=200)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1000, completion_tokens=0, created_at=300)
    # half-open [150, 300): only the 200 record
    window = ledger.rollup("provider", start=150, end=300)
    assert window["openai"]["record_count"] == 1
    assert ledger.total(start=150, end=300)["cost_amount"] == 2.0


def test_report_envelope_sorts_by_cost_desc_and_includes_grand_total() -> None:
    ledger = _priced_ledger()
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1000, completion_tokens=0,
                        attribution={"team": "cheap"})  # 2
    ledger.record_usage(provider="anthropic", model="claude-y", prompt_tokens=1000, completion_tokens=1000,
                        attribution={"team": "pricey"})  # 9
    report = ledger.report("team")
    assert [item["dimension_value"] for item in report["items"]] == ["pricey", "cheap"]
    assert report["grand_total"]["cost_amount"] == 11.0


def test_sql_ledger_store_on_sqlite_creates_objects_and_rolls_up() -> None:
    conn = sqlite3.connect(":memory:")
    store = SqlLedgerStore(conn, paramstyle="qmark")
    ledger = _priced_ledger(store=store)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1000, completion_tokens=1000,
                        attribution={"company": "acme"})
    ledger.record_usage(provider="anthropic", model="claude-y", prompt_tokens=1000, completion_tokens=1000,
                        attribution={"company": "acme"})

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"llm_usage_records", "cost_attribution_dimensions", "llm_price_entries"} <= tables
    assert conn.execute("SELECT count(*) FROM llm_usage_records").fetchone()[0] == 2
    # dimension catalog seeded
    assert conn.execute("SELECT count(*) FROM cost_attribution_dimensions").fetchone()[0] == len(ATTRIBUTION_DIMENSIONS)

    by_company = ledger.rollup("company")
    assert by_company["acme"]["cost_amount"] == 15.0  # 6 + 9


def test_ledger_table_names_follow_two_word_snake_case() -> None:
    for name in ("llm_usage_records", "cost_attribution_dimensions", "llm_price_entries"):
        assert is_two_word_snake_case(name)


def test_dimension_catalog_covers_all_required_dimensions() -> None:
    names = {entry["dimension_name"] for entry in dimension_catalog()}
    assert names == {"account", "service", "upstream_api", "model_name", "team", "group", "company"}


class _RecordingBackend:
    """Working ledger backend that records appends and returns fixed query rows."""

    def __init__(self, rows=None) -> None:
        self.rows = rows if rows is not None else []
        self.appended = []

    def append(self, record) -> None:
        self.appended.append(record)

    def query(self, start=None, end=None):
        return self.rows


class _BlockingBackend:
    """Ledger backend whose ``append`` blocks until ``release`` is set."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.appended = []

    def append(self, record) -> None:
        self.started.set()
        self.release.wait(timeout=5.0)
        self.appended.append(record)

    def query(self, start=None, end=None):
        return []


class _RaisingTelemetrySink:
    """Telemetry sink that always raises, to exercise best-effort swallowing."""

    def emit_usage(self, event) -> None:
        raise RuntimeError("telemetry backend is down")


def _sample_record(usage_record_id: str = "usage_sample") -> UsageRecord:
    return UsageRecord(
        usage_record_id=usage_record_id,
        created_at=100,
        workflow_run_id=None,
        request_channel="sync",
        route_mode=None,
        provider_name="openai",
        model_name="gpt-x",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_amount=1.0,
        currency_code="USD",
    )


def test_in_memory_telemetry_sink_trims_to_max_events() -> None:
    # Covers cost_ledger.py:346 (event-list trimming when over capacity).
    sink = InMemoryUsageTelemetrySink(max_events=2)
    for index in range(3):
        sink.emit_usage(
            UsageTelemetryEvent(name=f"event-{index}", attributes={}, metrics={})
        )
    kept = [event.name for event in sink.events()]
    assert kept == ["event-1", "event-2"]


def test_emit_usage_event_swallows_sink_failure() -> None:
    # Covers cost_ledger.py:379-381 (best-effort telemetry export swallow).
    ledger = _priced_ledger(telemetry_sink=_RaisingTelemetrySink())
    record = ledger.record_usage(
        provider="openai", model="gpt-x", prompt_tokens=10, completion_tokens=5
    )
    # The completion still succeeds even though the telemetry sink raised.
    assert record.usage_record_id.startswith("usage_")
    assert len(ledger.records()) == 1


def test_non_blocking_store_rejects_zero_queue_size() -> None:
    # Covers cost_ledger.py:395 (queue_size validation).
    try:
        NonBlockingLedgerStore(_RecordingBackend(), queue_size=0)
    except ValueError as exc:
        assert "queue_size must be at least 1" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for queue_size < 1")


def test_non_blocking_store_drops_record_when_queue_full() -> None:
    # Covers cost_ledger.py:412-422 (queue.Full drop path).
    backend = _BlockingBackend()
    sink = InMemoryUsageTelemetrySink()
    store = NonBlockingLedgerStore(backend, queue_size=1, telemetry_sink=sink)
    store.append(_sample_record("usage_a"))
    # Worker has dequeued A and is now blocked inside append(A): the queue is empty.
    assert backend.started.wait(timeout=5.0)
    store.append(_sample_record("usage_b"))  # fills the single queue slot
    store.append(_sample_record("usage_c"))  # overflows -> dropped
    health = store.telemetry_health()
    assert health["records_dropped"] == 1
    dropped_states = [
        event.attributes["contextual_orchestrator.usage.export_state"]
        for event in sink.events()
    ]
    assert "dropped" in dropped_states
    backend.release.set()
    assert store.flush(timeout=5.0)


def test_non_blocking_store_query_delegates_to_backend() -> None:
    # Covers cost_ledger.py:431 (query delegates to backend store).
    backend = _RecordingBackend(rows=[{"created_at": 42}])
    store = NonBlockingLedgerStore(backend, queue_size=4)
    assert store.query(start=0, end=100) == [{"created_at": 42}]


def test_non_blocking_store_flush_times_out_while_worker_busy() -> None:
    # Covers cost_ledger.py:438 (flush returns False on timeout).
    backend = _BlockingBackend()
    store = NonBlockingLedgerStore(backend, queue_size=4)
    store.append(_sample_record())
    assert backend.started.wait(timeout=5.0)  # worker blocked; unfinished_tasks > 0
    assert store.flush(timeout=0.0) is False
    backend.release.set()
    assert store.flush(timeout=5.0) is True


def test_non_blocking_store_marks_stored_on_success() -> None:
    # Covers cost_ledger.py:463-464 (worker success path marks stored + emits).
    backend = _RecordingBackend()
    sink = InMemoryUsageTelemetrySink()
    store = NonBlockingLedgerStore(backend, queue_size=4, telemetry_sink=sink)
    store.append(_sample_record())
    assert store.flush(timeout=5.0)
    assert store.telemetry_health()["records_stored"] == 1
    stored_states = [
        event.attributes["contextual_orchestrator.usage.export_state"]
        for event in sink.events()
    ]
    assert "stored" in stored_states
    assert len(backend.appended) == 1


def test_in_memory_ledger_store_len_reports_row_count() -> None:
    # Covers cost_ledger.py:493 (InMemoryLedgerStore.__len__). Appends are made
    # directly because an empty store is falsy (``store or ...`` in CostLedger).
    store = InMemoryLedgerStore()
    assert len(store) == 0
    store.append(_sample_record("usage_1"))
    store.append(_sample_record("usage_2"))
    assert len(store) == 2


def test_sql_ledger_store_query_filters_by_time_window() -> None:
    # Covers cost_ledger.py:617-618, 620-621 (start/end WHERE-clause builder).
    conn = sqlite3.connect(":memory:")
    store = SqlLedgerStore(conn, paramstyle="qmark")
    ledger = _priced_ledger(store=store)
    for created_at in (100, 200, 300):
        ledger.record_usage(
            provider="openai",
            model="gpt-x",
            prompt_tokens=1,
            completion_tokens=1,
            created_at=created_at,
        )
    windowed = store.query(start=150, end=300)  # half-open: only created_at == 200
    assert len(windowed) == 1
    assert windowed[0]["created_at"] == 200


def test_non_blocking_store_wrapping_via_flag() -> None:
    # Covers cost_ledger.py:659 (CostLedger wraps store when non_blocking_store=True).
    ledger = _priced_ledger(non_blocking_store=True)
    assert isinstance(ledger.store, NonBlockingLedgerStore)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1000, completion_tokens=0)
    assert ledger.flush(timeout=5.0)
    assert ledger.total()["cost_amount"] == 2.0


def test_record_usage_accepts_attribution_dimensions_instance() -> None:
    # Covers cost_ledger.py:686 (attribution passed as AttributionDimensions).
    ledger = _priced_ledger()
    record = ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=10,
        completion_tokens=10,
        attribution=AttributionDimensions(team="alpha", company="acme"),
    )
    row = record.as_dict()
    assert row["team_name"] == "alpha"
    assert row["company_name"] == "acme"


def test_inline_store_failure_marks_health_and_emits_error() -> None:
    # Covers cost_ledger.py:714-716 (inline append failure) and 837-839
    # (_mark_inline_failure counters).
    sink = InMemoryUsageTelemetrySink()
    ledger = _priced_ledger(store=_FailingLedgerStore(), telemetry_sink=sink)
    record = ledger.record_usage(
        provider="openai", model="gpt-x", prompt_tokens=10, completion_tokens=5
    )
    assert record.usage_record_id.startswith("usage_")
    health = ledger.telemetry_health()
    assert health["records_accepted"] == 1
    assert health["store_failures"] == 1
    assert health["last_error_type"] == "RuntimeError"
    error_states = [
        event.attributes["contextual_orchestrator.usage.export_state"]
        for event in sink.events()
    ]
    assert "export_error" in error_states
    # The DB/client message must never leak into telemetry payload.
    assert "secret prompt" not in repr(sink.events())


def test_flush_returns_true_for_store_without_flush_method() -> None:
    # Covers cost_ledger.py:738 (flush no-op when the store has no flush()).
    ledger = _priced_ledger()  # default InMemoryLedgerStore has no flush()
    assert ledger.flush() is True
    assert ledger.flush(timeout=1.0) is True


if __name__ == "__main__":  # pragma: no cover
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
    print("ok")
