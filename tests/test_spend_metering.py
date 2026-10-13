"""Tenant metering records, stores, and aggregation (ADR 0138)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contextual_orchestrator.domain.budget import BudgetScope
from contextual_orchestrator.domain.money import Money
from contextual_orchestrator.domain.tenancy import TenantBudget, VirtualKey, hash_virtual_key
from contextual_orchestrator.spend_guard import SpendGuard
from contextual_orchestrator.spend_metering import (
    RUN_SUMMARY_SCHEMA,
    InMemorySpendLedgerStore,
    JsonlSpendLedgerStore,
    MeteredUsage,
    aggregate_usage,
    spent_in_scope,
    summarize_run,
    write_run_usage_summary,
)

_LEDGER = SpendGuard().ledger


def _entry(
    tenant: str = "acme",
    provider: str = "openai",
    model: str = "gpt",
    cost: str | None = "0.01",
    created_at: int = 1000,
    run_id: str = "run_1",
    key_id: str | None = None,
    measured: bool = True,
) -> MeteredUsage:
    record = _LEDGER.record_usage(
        provider=provider,
        model=model,
        prompt_tokens=100 if measured else 0,
        completion_tokens=50 if measured else 0,
        workflow_run_id=run_id,
        measurement_status="measured" if measured else "unavailable",
        created_at=created_at,
    )
    return MeteredUsage(
        tenant_id=tenant,
        run_id=run_id,
        call_status="ok",
        record=record,
        charged_cost=None if cost is None else Money.usd(cost),
        cost_source="unknown" if cost is None else "price_book",
        virtual_key_id=key_id,
    )


def test_metered_usage_round_trips_and_flags_unknown_price() -> None:
    """Rows carry tenant, run, provider, model, tokens, cost, status, and time."""
    entry = _entry(cost=None)
    row = entry.as_dict()
    assert row["price_unknown"] is True and row["charged_cost_usd"] is None
    assert row["record"]["provider_name"] == "openai"
    assert row["record"]["prompt_tokens"] == 100
    assert MeteredUsage.from_dict(json.loads(json.dumps(row))) == entry


def test_metered_usage_rejects_inconsistent_cost_source() -> None:
    """A null cost must be labelled unknown, and only then."""
    record = _entry().record
    with pytest.raises(ValueError):
        MeteredUsage("t", "r", "ok", record, None, "price_book")
    with pytest.raises(ValueError):
        MeteredUsage("t", "r", "weird", record, Money.usd(0), "zero_cost")


def test_in_memory_store_dedupes_by_record_id() -> None:
    """The same usage record is never charged twice."""
    store = InMemorySpendLedgerStore()
    entry = _entry()
    assert store.append_usage(entry) is True
    assert store.append_usage(entry) is False
    assert len(store.usage_entries()) == 1


def test_jsonl_store_replays_usage_keys_and_budgets(tmp_path: Path) -> None:
    """The durable adapter rebuilds the same state from its append-only file."""
    path = tmp_path / "ledger.jsonl"
    store = JsonlSpendLedgerStore(path)
    key = VirtualKey(hash_virtual_key("sk-co-" + "k" * 40), "acme", Money.usd(5), None, None, 10)
    store.put_virtual_key(key)
    store.put_tenant_budget(TenantBudget("acme", Money.usd(50), 86400, None, 10))
    store.append_usage(_entry())
    replayed = JsonlSpendLedgerStore(path)
    assert replayed.virtual_key(key.key_hash) == key
    assert replayed.tenant_budget("acme").max_budget == Money.usd(50)
    assert [e.record.usage_record_id for e in replayed.usage_entries()] == [
        e.record.usage_record_id for e in store.usage_entries()
    ]
    assert "sk-co-" not in path.read_text()


def test_jsonl_store_quarantines_truncated_final_line(tmp_path: Path) -> None:
    """A crash mid-append loses only that line, and later appends stay parseable."""
    path = tmp_path / "ledger.jsonl"
    JsonlSpendLedgerStore(path).append_usage(_entry(run_id="run_a"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"event": "usage", "data": {"tenant')
    store = JsonlSpendLedgerStore(path)
    assert store.skipped_partial_lines == 1
    assert Path(f"{path}.partial").exists()
    store.append_usage(_entry(run_id="run_b"))
    assert len(JsonlSpendLedgerStore(path).usage_entries()) == 2


def test_jsonl_store_refuses_corrupt_middle_line(tmp_path: Path) -> None:
    """Corruption before the tail raises instead of silently under-counting spend."""
    path = tmp_path / "ledger.jsonl"
    store = JsonlSpendLedgerStore(path)
    store.append_usage(_entry(run_id="run_a"))
    lines = path.read_text().splitlines()
    path.write_text("not json\n" + "\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="corrupt spend ledger line 1"):
        JsonlSpendLedgerStore(path)


def test_aggregate_by_tenant_provider_model_and_window() -> None:
    """Roll-ups by tenant, tenant+provider/model, and a time window."""
    entries = [
        _entry("acme", "openai", "gpt", "0.01", 1000),
        _entry("acme", "openai", "gpt", "0.02", 2000),
        _entry("acme", "openrouter", "llama", None, 2500),
        _entry("globex", "openai", "gpt", "0.05", 3000),
    ]
    by_tenant = {row["tenant_id"]: row for row in aggregate_usage(entries)}
    assert by_tenant["acme"]["calls"] == 3
    assert by_tenant["acme"]["charged_cost"] == pytest.approx(0.03)
    assert by_tenant["acme"]["cost_complete"] is False
    assert by_tenant["globex"]["cost_complete"] is True
    detailed = aggregate_usage(entries, group_by=("tenant_id", "provider_name", "model_name"))
    assert {(r["tenant_id"], r["provider_name"], r["model_name"]) for r in detailed} == {
        ("acme", "openai", "gpt"), ("acme", "openrouter", "llama"), ("globex", "openai", "gpt"),
    }
    windowed = aggregate_usage(entries, start=1500, end=3000)
    assert [(r["tenant_id"], r["calls"]) for r in windowed] == [("acme", 2)]
    with pytest.raises(ValueError):
        aggregate_usage(entries, group_by=("secret_field",))


def test_unmeasured_calls_are_counted_not_invented() -> None:
    """Calls without usage add no tokens but are counted as unmeasured."""
    rows = aggregate_usage([_entry(measured=False, cost=None)])
    assert rows[0]["prompt_tokens"] == 0 and rows[0]["unmeasured_calls"] == 1


def test_spent_in_scope_filters_by_scope_and_window() -> None:
    """Key and tenant spend only include their own entries in the current period."""
    entries = [
        _entry("acme", cost="1", created_at=100, key_id="vk_a"),
        _entry("acme", cost="2", created_at=200, key_id="vk_b"),
        _entry("acme", cost=None, created_at=300, key_id="vk_a"),
        _entry("globex", cost="4", created_at=300),
    ]
    assert spent_in_scope(entries, scope=BudgetScope.TENANT, scope_id="acme", since=None) == (Money.usd(3), 1)
    assert spent_in_scope(entries, scope=BudgetScope.VIRTUAL_KEY, scope_id="vk_a", since=None) == (Money.usd(1), 1)
    assert spent_in_scope(entries, scope=BudgetScope.TENANT, scope_id="acme", since=150) == (Money.usd(2), 1)


def test_run_summary_artifact_is_written_atomically(tmp_path: Path) -> None:
    """The per-run artifact has a stable schema and only that run's calls."""
    entries = [_entry(run_id="run_1"), _entry(run_id="run_2", cost="0.5")]
    summary = summarize_run(entries, run_id="run_1", tenant_id="acme", dropped_providers={"bytez": "x"})
    assert summary["schema"] == RUN_SUMMARY_SCHEMA
    assert len(summary["calls"]) == 1
    assert summary["totals"][0]["charged_cost"] == pytest.approx(0.01)
    target = write_run_usage_summary(tmp_path / "out" / "summary.json", summary)
    assert json.loads(target.read_text())["dropped_providers"] == {"bytez": "x"}
    assert not [p for p in target.parent.iterdir() if p.name.startswith(".run-usage-")]
