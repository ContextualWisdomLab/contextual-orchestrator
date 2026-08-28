"""Canonical usage export integration tests."""

from __future__ import annotations

from contextual_orchestrator.cost_ledger import (
    CostLedger,
    InMemoryUsageTelemetrySink,
    PriceBook,
    PriceEntry,
    UsageRecord,
)
from contextual_orchestrator.metering import CanonicalUsageRecordSink
from contextual_orchestrator.kv_config import InMemoryConfigStore


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
    assert queued[0]["identity"] == {"tenant_reference": "urn:cwl:tenant:test"}


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
