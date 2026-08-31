"""Cost ledger: price computation, per-request writes, multi-dimensional rollup."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.cost_ledger import (  # noqa: E402
    ATTRIBUTION_DIMENSIONS,
    CostLedger,
    InMemoryUsageTelemetrySink,
    NonBlockingLedgerStore,
    PriceBook,
    PriceEntry,
    SCHEMA_SQL,
    SqlLedgerStore,
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


class _PyformatCursor:
    def __init__(self, connection) -> None:
        self._connection = connection
        self._cursor = connection._sqlite.cursor()
        self._information_schema_rows = None

    def execute(self, statement, params=()):
        if statement.count("%s") != len(params):
            raise AssertionError("pyformat placeholders and values diverged")
        self._connection.executions.append((statement, tuple(params)))
        self._information_schema_rows = None
        if "information_schema.columns" in statement:
            self._cursor.execute("PRAGMA table_info(llm_usage_records)")
            self._information_schema_rows = [(row[1],) for row in self._cursor.fetchall()]
            return self
        self._cursor.execute(statement.replace("%s", "?"), tuple(params))
        return self

    def fetchone(self):
        if self._information_schema_rows is not None:
            return self._information_schema_rows.pop(0) if self._information_schema_rows else None
        return self._cursor.fetchone()

    def fetchall(self):
        if self._information_schema_rows is not None:
            rows = self._information_schema_rows
            self._information_schema_rows = None
            return rows
        return self._cursor.fetchall()


class _PyformatConnection:
    def __init__(self) -> None:
        self._sqlite = sqlite3.connect(":memory:")
        self.executions = []

    def cursor(self):
        return _PyformatCursor(self)

    def commit(self) -> None:
        self._sqlite.commit()


def test_price_computation_uses_per_1k_rates() -> None:
    ledger = _priced_ledger()
    # 1000 prompt * $2/1k + 500 completion * $4/1k = 2.0 + 2.0 = 4.0
    record = ledger.record_usage(
        provider="openai", model="gpt-x", prompt_tokens=1000, completion_tokens=500
    )
    assert record.cost_amount == 4.0
    assert record.currency_code == "USD"
    assert record.total_tokens == 1500
    assert record.measurement_status == "measured"


def test_usage_measurement_status_rejects_unknown_provenance() -> None:
    """Usage rows cannot persist an unrecognized measurement claim."""
    with pytest.raises(ValueError, match="measurement_status"):
        _priced_ledger().record_usage(
            provider="openai",
            model="gpt-x",
            prompt_tokens=1,
            completion_tokens=1,
            measurement_status="guessed",
        )


def test_stable_usage_identity_is_idempotent() -> None:
    ledger = _priced_ledger()
    for _ in range(2):
        ledger.record_usage(
            provider="openai", model="gpt-x", prompt_tokens=7,
            completion_tokens=2, usage_record_id="usage_video_stable",
        )
    assert len(ledger.records()) == 1


def test_sql_stable_usage_identity_is_idempotent() -> None:
    ledger = _priced_ledger(
        store=SqlLedgerStore(sqlite3.connect(":memory:"), paramstyle="qmark")
    )
    for _ in range(2):
        ledger.record_usage(
            provider="openai", model="gpt-x", prompt_tokens=7,
            completion_tokens=2, usage_record_id="usage_video_stable",
            attribution={"team": "first" if _ == 0 else "revised"},
        )
    assert len(ledger.records()) == 1
    assert ledger.records()[0]["team_name"] == "first"


def test_unpriced_model_costs_zero_and_still_records() -> None:
    ledger = _priced_ledger()
    record = ledger.record_usage(
        provider="mystery", model="unpriced", prompt_tokens=100, completion_tokens=50
    )
    assert record.cost_amount == 0.0
    # The zero must be distinguishable from a real free price: an unpriced
    # provider/model is unknown, never fabricated as $0.00.
    assert record.price_known is False
    assert len(ledger.records()) == 1


def test_priced_model_marks_price_known_true() -> None:
    ledger = _priced_ledger()
    record = ledger.record_usage(
        provider="openai", model="gpt-x", prompt_tokens=100, completion_tokens=50
    )
    assert record.price_known is True


def test_compute_cost_returns_price_known_flag() -> None:
    """PriceBook.compute_cost's 3-tuple distinguishes known from unknown price."""
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(
        PriceEntry("openai", "gpt-x", prompt_price_per_1k=2.0, completion_price_per_1k=4.0)
    )

    priced = price_book.compute_cost("openai", "gpt-x", 1000, 500)
    assert priced == (4.0, "USD", True)

    unpriced = price_book.compute_cost("mystery", "unpriced", 100, 50)
    assert unpriced == (0.0, "USD", False)


def test_provider_wildcard_price_entry() -> None:
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("openai", "*", prompt_price_per_1k=1.0, completion_price_per_1k=1.0))
    ledger = CostLedger(price_book)
    record = ledger.record_usage(provider="openai", model="any-model", prompt_tokens=1000, completion_tokens=1000)
    assert record.cost_amount == 2.0


def test_corrupt_specific_row_still_falls_back_to_wildcard_price() -> None:
    """A malformed provider:model row must not shadow a valid provider:* row."""
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("openai", "*", prompt_price_per_1k=1.0, completion_price_per_1k=1.0))
    config.set("llm_price_entries", "openai:broken-model", {"prompt_price_per_1k": "not-a-number"})

    entry = price_book.get_price("openai", "broken-model")

    assert entry is not None
    assert entry.prompt_price_per_1k == 1.0
    assert entry.completion_price_per_1k == 1.0


def test_underflowing_positive_price_row_falls_back_to_wildcard() -> None:
    """A nonzero KV price that underflows to 0.0 must not be treated as free."""
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("openai", "*", prompt_price_per_1k=1.0, completion_price_per_1k=1.0))
    config.set(
        "llm_price_entries",
        "openai:underflow-model",
        {"prompt_price_per_1k": "1e-10000", "completion_price_per_1k": "1e-10000"},
    )

    entry = price_book.get_price("openai", "underflow-model")

    assert entry is not None
    assert entry.prompt_price_per_1k == 1.0
    assert entry.completion_price_per_1k == 1.0


def test_overflowing_price_row_falls_back_to_wildcard() -> None:
    """A Decimal-finite KV price whose float() conversion overflows to inf must not be treated as valid."""
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("openai", "*", prompt_price_per_1k=1.0, completion_price_per_1k=1.0))
    config.set(
        "llm_price_entries",
        "openai:overflow-model",
        {"prompt_price_per_1k": "1e10000", "completion_price_per_1k": "1e10000"},
    )

    entry = price_book.get_price("openai", "overflow-model")

    assert entry is not None
    assert entry.prompt_price_per_1k == 1.0
    assert entry.completion_price_per_1k == 1.0


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


def test_rollup_report_total_break_down_cost_by_measurement_status() -> None:
    """cost_amount stays a flat sum; the new by-status fields attribute it."""
    ledger = _priced_ledger()
    ledger.record_usage(
        provider="openai", model="gpt-x", prompt_tokens=1000, completion_tokens=0,
        measurement_status="measured",
    )  # 2.0, priced
    ledger.record_usage(
        provider="openai", model="gpt-x", prompt_tokens=500, completion_tokens=0,
        measurement_status="estimated",
    )  # 1.0, priced
    ledger.record_usage(
        provider="mystery", model="unpriced", prompt_tokens=1000, completion_tokens=1000,
        measurement_status="unavailable",
    )  # 0.0, unpriced

    total = ledger.total()
    assert total["cost_amount"] == 3.0  # unchanged, backward-compatible flat total
    assert total["cost_amount_by_status"] == {
        "measured": 2.0, "estimated": 1.0, "unavailable": 0.0,
    }
    assert total["record_count_by_status"] == {
        "measured": 1, "estimated": 1, "unavailable": 1,
    }
    # The breakdown must sum back to the flat total exactly.
    assert sum(total["cost_amount_by_status"].values()) == total["cost_amount"]

    by_provider = ledger.rollup("provider")
    assert by_provider["openai"]["cost_amount"] == 3.0
    assert by_provider["openai"]["cost_amount_by_status"] == {
        "measured": 2.0, "estimated": 1.0, "unavailable": 0.0,
    }
    assert by_provider["openai"]["record_count_by_status"] == {
        "measured": 1, "estimated": 1, "unavailable": 0,
    }
    assert by_provider["mystery"]["cost_amount_by_status"]["unavailable"] == 0.0
    assert by_provider["mystery"]["record_count_by_status"]["unavailable"] == 1

    report = ledger.report("provider")
    assert report["grand_total"] == total


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


def test_sql_ledger_persists_price_known_flag() -> None:
    """price_known round-trips through the SQL store's satellite table."""
    conn = sqlite3.connect(":memory:")
    store = SqlLedgerStore(conn, paramstyle="qmark")
    ledger = _priced_ledger(store=store)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1000, completion_tokens=0)
    ledger.record_usage(provider="mystery", model="unpriced", prompt_tokens=1000, completion_tokens=0)

    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='usage_price_knowledge'"
    ).fetchone() == ("usage_price_knowledge",)

    rows = {row["provider_name"]: row for row in store.query()}
    assert bool(rows["openai"]["price_known"]) is True
    assert bool(rows["mystery"]["price_known"]) is False


def test_table_columns_honors_its_argument_on_qmark() -> None:
    """The qmark branch must inspect the requested table, not a hardcoded one."""
    conn = sqlite3.connect(":memory:")
    store = SqlLedgerStore(conn, paramstyle="qmark")
    columns = store._table_columns("llm_usage_records")
    assert "cost_amount" in columns
    with pytest.raises(ValueError, match="llm_price_entries"):
        store._table_columns("llm_price_entries")


def test_sql_ledger_stores_descriptive_attribution_in_normalized_tables() -> None:
    """Keep descriptive values out of the per-request fact row."""
    connection = sqlite3.connect(":memory:")
    store = SqlLedgerStore(connection, paramstyle="qmark")
    ledger = _priced_ledger(store=store)
    ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=10,
        completion_tokens=5,
        attribution={
            "account": "acct-1",
            "service": "search",
            "team": "alpha",
            "group": "platform",
            "company": "acme",
        },
    )

    columns = {row[1] for row in connection.execute("PRAGMA table_info(llm_usage_records)")}
    assert {"account_name", "service_name", "team_name", "group_name", "company_name"}.isdisjoint(columns)
    assert connection.execute("SELECT COUNT(*) FROM usage_record_attributions").fetchone() == (5,)
    assert connection.execute("SELECT COUNT(*) FROM cost_attribution_values").fetchone() == (5,)
    assert store.query()[0]["account_name"] == "acct-1"
    assert store.query()[0]["upstream_api"] == "openai"
    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO usage_record_attributions "
            "(usage_record_id, dimension_name, dimension_value) VALUES (?, ?, ?)",
            ("missing_usage", "team", "alpha"),
        )
    usage_record_id = store.query()[0]["usage_record_id"]
    connection.execute("DELETE FROM llm_usage_records WHERE usage_record_id = ?", (usage_record_id,))
    assert connection.execute(
        "SELECT COUNT(*) FROM usage_record_attributions WHERE usage_record_id = ?",
        (usage_record_id,),
    ).fetchone() == (0,)


def test_sql_ledger_enables_foreign_keys_and_cascades_attribution_rows() -> None:
    """Keep relational attribution rows attached to their usage fact."""
    connection = sqlite3.connect(":memory:")
    store = SqlLedgerStore(connection, paramstyle="qmark")
    ledger = _priced_ledger(store=store)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1, completion_tokens=1)
    usage_record_id = store.query()[0]["usage_record_id"]

    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    connection.execute("DELETE FROM llm_usage_records WHERE usage_record_id = ?", (usage_record_id,))
    assert connection.execute(
        "SELECT COUNT(*) FROM usage_record_attributions WHERE usage_record_id = ?",
        (usage_record_id,),
    ).fetchone() == (0,)


def test_sql_ledger_rolls_back_failed_append_before_next_write() -> None:
    """A failed multi-row append must not leak into the next committed write."""
    connection = sqlite3.connect(":memory:")
    store = SqlLedgerStore(connection, paramstyle="qmark")
    ledger = _priced_ledger(store=store)
    original = SqlLedgerStore._insert_normalized_attribution
    calls = 0

    def fail_after_first_append(store_instance, cursor, row) -> None:
        """Inject one failure after the first record's normalized writes."""
        nonlocal calls
        calls += 1
        original(store_instance, cursor, row)
        if calls == 1:
            raise RuntimeError("simulated attribution write failure")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(SqlLedgerStore, "_insert_normalized_attribution", fail_after_first_append)
        failed = ledger.record_usage(
            provider="openai",
            model="gpt-x",
            prompt_tokens=10,
            completion_tokens=5,
            attribution={"team": "failed-team"},
        )

    assert connection.execute(
        "SELECT COUNT(*) FROM llm_usage_records WHERE usage_record_id = ?",
        (failed.usage_record_id,),
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT COUNT(*) FROM usage_record_attributions WHERE usage_record_id = ?",
        (failed.usage_record_id,),
    ).fetchone() == (0,)

    successful = ledger.record_usage(
        provider="openai",
        model="gpt-x",
        prompt_tokens=20,
        completion_tokens=5,
        attribution={"team": "successful-team"},
    )
    rows = store.query()
    assert [row["usage_record_id"] for row in rows] == [successful.usage_record_id]
    assert rows[0]["team_name"] == "successful-team"


def test_sql_ledger_migrates_flattened_usage_rows() -> None:
    """Migrate legacy fact rows without changing the query contract."""
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE llm_usage_records (
            usage_record_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL,
            workflow_run_id TEXT, request_channel TEXT NOT NULL, route_mode TEXT,
            provider_name TEXT, model_name TEXT, account_name TEXT,
            service_name TEXT, upstream_api TEXT, team_name TEXT,
            group_name TEXT, company_name TEXT, prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
            cost_amount REAL NOT NULL, currency_code TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO llm_usage_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "usage_legacy",
            123,
            None,
            "sync",
            None,
            "openai",
            "gpt-x",
            "acct-1",
            None,
            "openai",
            None,
            "platform",
            "acme",
            1,
            2,
            3,
            4.5,
            "USD",
        ),
    )
    connection.commit()

    store = SqlLedgerStore(connection, paramstyle="qmark")
    row = store.query()[0]
    columns = {entry[1] for entry in connection.execute("PRAGMA table_info(llm_usage_records)")}
    assert "account_name" not in columns
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("llm_usage_records_legacy",),
    ).fetchone() is None
    assert row["usage_record_id"] == "usage_legacy"
    assert row["account_name"] == "acct-1"
    assert row["service_name"] == "unattributed"
    assert row["team_name"] == "unattributed"
    assert row["company_name"] == "acme"
    # A flattened legacy row predates the price_known signal: whether its
    # stored cost reflects a real price is unknown, so migration marks it
    # unknown rather than assuming it was known.
    assert bool(row["price_known"]) is False


def test_sql_ledger_maps_null_legacy_attribution_to_unattributed() -> None:
    """Migrate nullable legacy labels without violating normalized constraints."""
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE llm_usage_records (
            usage_record_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL,
            workflow_run_id TEXT, request_channel TEXT NOT NULL, route_mode TEXT,
            provider_name TEXT, model_name TEXT, account_name TEXT,
            service_name TEXT, upstream_api TEXT, team_name TEXT,
            group_name TEXT, company_name TEXT, prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
            cost_amount REAL NOT NULL, currency_code TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO llm_usage_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "usage_nullable",
            123,
            None,
            "sync",
            None,
            "openai",
            "gpt-x",
            None,
            None,
            None,
            None,
            None,
            None,
            1,
            2,
            3,
            4.5,
            "USD",
        ),
    )
    connection.commit()

    row = SqlLedgerStore(connection, paramstyle="qmark").query()[0]
    assert row["account_name"] == "unattributed"
    assert row["service_name"] == "unattributed"
    assert row["team_name"] == "unattributed"


def test_sql_ledger_rolls_back_seeded_catalog_legacy_migration() -> None:
    """Restore the flattened ledger when a seeded-catalog copy fails midway."""
    connection = sqlite3.connect(":memory:")
    for statement in SCHEMA_SQL.strip().split(";")[:2]:
        connection.execute(statement)
    connection.executemany(
        "INSERT INTO cost_attribution_dimensions "
        "(dimension_name, dimension_label, dimension_order) VALUES (?, ?, ?)",
        [(name, name.title(), order) for order, name in enumerate(ATTRIBUTION_DIMENSIONS)],
    )
    connection.execute(
        """
        CREATE TABLE llm_usage_records (
            usage_record_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL,
            workflow_run_id TEXT, request_channel TEXT NOT NULL, route_mode TEXT,
            provider_name TEXT, model_name TEXT, account_name TEXT,
            service_name TEXT, upstream_api TEXT, team_name TEXT,
            group_name TEXT, company_name TEXT, prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
            cost_amount REAL NOT NULL, currency_code TEXT NOT NULL
        )
        """
    )
    legacy_row = (
        "usage_seeded", 123, None, "sync", None, "openai", "gpt-x",
        "acct-1", "search", "openai", "alpha", "platform", "acme", 1, 2, 3, 4.5, "USD",
    )
    connection.executemany(
        "INSERT INTO llm_usage_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [legacy_row, ("usage_seeded_2", *legacy_row[1:])],
    )
    connection.commit()

    calls = 0
    original = SqlLedgerStore._insert_normalized_attribution

    def fail_on_second_row(store, cursor, row) -> None:
        """Inject one deterministic copy failure after the first row."""
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated legacy copy failure")
        original(store, cursor, row)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(SqlLedgerStore, "_insert_normalized_attribution", fail_on_second_row)
        with pytest.raises(RuntimeError, match="simulated legacy copy failure"):
            SqlLedgerStore(connection, paramstyle="qmark")

    columns = {row[1] for row in connection.execute("PRAGMA table_info(llm_usage_records)")}
    assert "account_name" in columns
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("llm_usage_records_legacy",),
    ).fetchone() is None
    assert connection.execute("SELECT COUNT(*) FROM llm_usage_records").fetchone() == (2,)
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("usage_record_attributions",),
    ).fetchone() is None


def test_sql_ledger_rejects_ambiguous_legacy_migration_without_renaming_source() -> None:
    """Fail closed when both schema generations coexist; source stays intact."""
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE llm_usage_records (usage_record_id TEXT, account_name TEXT)"
    )
    connection.execute("CREATE TABLE llm_usage_records_legacy (legacy_id TEXT)")
    connection.commit()

    # Two generations coexisting is ambiguous about which rows are
    # authoritative, so construction must fail closed before any rename.
    with pytest.raises(RuntimeError, match="both llm_usage_records"):
        SqlLedgerStore(connection, paramstyle="qmark")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(llm_usage_records)")}
    assert "account_name" in columns


def test_sql_ledger_serializes_shared_sqlite_connection_writes() -> None:
    """Concurrent callers cannot overlap transactions on one SQLite connection."""
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    store = SqlLedgerStore(connection, paramstyle="qmark")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                lambda index: store.append(
                    _guard_usage_record(usage_record_id=f"usage_concurrent_{index}")
                ),
                range(32),
            )
        )

    assert len(store.query()) == 32


def test_flattened_migration_names_missing_columns_before_rename() -> None:
    """Reject incomplete flattened schemas without mutating their table name."""
    connection = sqlite3.connect(":memory:")
    columns = [
        "usage_record_id", "created_at", "workflow_run_id", "request_channel",
        "route_mode", "provider_name", "model_name", "prompt_tokens",
        "completion_tokens", "total_tokens", "cost_amount", "currency_code",
        "account_name", "upstream_api", "team_name", "group_name", "company_name",
    ]
    connection.execute("CREATE TABLE llm_usage_records (" + ", ".join(columns) + ")")
    connection.commit()

    with pytest.raises(RuntimeError, match="missing columns: service_name"):
        SqlLedgerStore(connection, paramstyle="qmark")

    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE name='llm_usage_records'"
    ).fetchone() == ("llm_usage_records",)


def _guard_usage_record(**overrides: object):
    """Build a full UsageRecord for ledger guard regression tests."""
    from contextual_orchestrator.cost_ledger import AttributionDimensions, UsageRecord

    defaults: dict = dict(
        usage_record_id="usage_guard_t1",
        created_at=1000,
        workflow_run_id=None,
        request_channel="sync",
        route_mode=None,
        provider_name="provider_one",
        model_name="model_one",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_amount=0.5,
        currency_code="USD",
        attribution=AttributionDimensions(),
    )
    defaults.update(overrides)
    return UsageRecord(**defaults)


def test_dual_generation_coexistence_fails_closed() -> None:
    """Both usage-table generations coexisting fails construction closed."""
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE llm_usage_records ("
        + ", ".join(
            [
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
            ]
        )
        + ")"
    )
    connection.execute(
        "CREATE TABLE llm_usage_records_legacy ("
        + ", ".join(
            [
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
                "account_name",
                "service_name",
                "upstream_api",
                "team_name",
                "group_name",
                "company_name",
            ]
        )
        + ")"
    )
    with pytest.raises(RuntimeError, match="both llm_usage_records"):
        SqlLedgerStore(connection, paramstyle="qmark")


def test_orphaned_legacy_generation_is_adopted_and_dropped() -> None:
    """A legacy-only table is rebuilt into the normalized schema, then dropped."""
    connection = sqlite3.connect(":memory:")
    legacy_columns = [
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
        "account_name",
        "service_name",
        "upstream_api",
        "team_name",
        "group_name",
        "company_name",
    ]
    connection.execute(
        "CREATE TABLE llm_usage_records_legacy (" + ", ".join(legacy_columns) + ")"
    )
    record = _guard_usage_record()
    flat = record.as_dict()
    connection.execute(
        "INSERT INTO llm_usage_records_legacy VALUES (?" + ",?" * 17 + ")",
        tuple(flat[column] for column in legacy_columns[:12])
        + ("acme_corp", "gateway_service", "openai", "model_one", "team_alpha", "group_beta"),
    )
    connection.commit()
    store = SqlLedgerStore(connection, paramstyle="qmark")
    rows = store.query(None, None)
    assert len(rows) == 1
    assert rows[0]["usage_record_id"] == "usage_guard_t1"
    # Adopted from a pre-price_known legacy table: unknown, not assumed known.
    assert bool(rows[0]["price_known"]) is False
    legacy_tables = connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='llm_usage_records_legacy'"
    ).fetchone()[0]
    assert legacy_tables == 0


def test_append_is_atomic_on_autocommit_connection() -> None:
    """A mid-append failure on an autocommit sqlite connection leaves no partial row."""
    connection = sqlite3.connect(":memory:", isolation_level=None)
    store = SqlLedgerStore(connection, paramstyle="qmark")
    original = store._insert_normalized_attribution
    armed = [True]

    def explode(cur, row):
        original(cur, row)
        if armed[0]:
            raise RuntimeError("simulated mid-append failure")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(store, "_insert_normalized_attribution", explode)
        with pytest.raises(RuntimeError, match="simulated mid-append failure"):
            store.append(_guard_usage_record())
    assert connection.execute("SELECT COUNT(*) FROM llm_usage_records").fetchone()[0] == 0
    assert (
        connection.execute("SELECT COUNT(*) FROM usage_record_attributions").fetchone()[0] == 0
    )
    armed[0] = False
    store.append(_guard_usage_record(usage_record_id="usage_guard_t2"))
    assert len(store.query(None, None)) == 1


def test_append_preserves_caller_owned_sqlite_transaction() -> None:
    connection = sqlite3.connect(":memory:")
    store = SqlLedgerStore(connection, paramstyle="qmark")
    connection.execute("BEGIN")

    store.append(_guard_usage_record())

    assert connection.in_transaction is True
    connection.rollback()
    assert store.query(None, None) == []


def test_sql_ledger_rejects_unknown_parameter_style() -> None:
    try:
        SqlLedgerStore(sqlite3.connect(":memory:"), paramstyle="named")
    except ValueError as exc:
        assert "paramstyle must be qmark or pyformat" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown DB-API parameter style must be rejected")


def test_sql_ledger_store_pyformat_binds_all_query_windows() -> None:
    connection = _PyformatConnection()
    store = SqlLedgerStore(connection, paramstyle="pyformat")
    assert any("information_schema.columns" in call[0] for call in connection.executions)
    assert not any("PRAGMA table_info" in call[0] for call in connection.executions)
    # An explicit BEGIN is sqlite3-specific; psycopg 3 starts its own implicit
    # transaction and would warn "there is already a transaction in progress"
    # if this store issued one too.
    assert not any(call[0].strip() == "BEGIN" for call in connection.executions)
    ledger = _priced_ledger(store=store)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=1000,
                        completion_tokens=0, created_at=100)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=2000,
                        completion_tokens=0, created_at=200)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=3000,
                        completion_tokens=0, created_at=300)

    assert [row["created_at"] for row in store.query()] == [100, 200, 300]
    assert [row["created_at"] for row in store.query(start=150)] == [200, 300]
    assert [row["created_at"] for row in store.query(end=300)] == [100, 200]
    assert [row["created_at"] for row in store.query(start=150, end=300)] == [200]
    insert_calls = [call for call in connection.executions if "INSERT INTO llm_usage_records" in call[0]]
    assert insert_calls[0][1][1] == 100
    query_calls = [call for call in connection.executions if "SELECT u.usage_record_id" in call[0]]
    assert [call[1] for call in query_calls[-4:]] == [(), (150,), (300,), (150, 300)]


def test_ledger_table_names_follow_two_word_snake_case() -> None:
    for name in (
        "llm_usage_records",
        "cost_attribution_dimensions",
        "llm_price_entries",
        "cost_attribution_values",
        "usage_record_attributions",
        "usage_measurements",
        "usage_price_knowledge",
    ):
        assert is_two_word_snake_case(name)


def test_dimension_catalog_covers_all_required_dimensions() -> None:
    names = {entry["dimension_name"] for entry in dimension_catalog()}
    assert names == {"account", "service", "upstream_api", "model_name", "team", "group", "company"}


if __name__ == "__main__":  # pragma: no cover
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
    print("ok")
