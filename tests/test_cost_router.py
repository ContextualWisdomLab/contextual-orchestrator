"""Cost-routing coordinator: records usage on every sync + batch completion."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    CostLedger,
    CostRoutingCoordinator,
    InMemoryConfigStore,
    InMemoryUsageTelemetrySink,
    ModelAgent,
    NonBlockingLedgerStore,
    PriceBook,
    PriceEntry,
    TaskOrchestrator,
)
from contextual_orchestrator.batch_routing import PgLlmBatchBackend  # noqa: E402


class _FailingLedgerStore:
    def append(self, record) -> None:
        raise RuntimeError("P2028 Transaction API error")

    def query(self, start=None, end=None):
        return []


def _coordinator(ledger=None) -> CostRoutingCoordinator:
    agents = [
        ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a", provider_name="mock",
                   tags=("reasoning", "coding", "writing"), priority=1),
    ]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("mock", "mock-a", prompt_price_per_1k=1.0, completion_price_per_1k=2.0))
    return CostRoutingCoordinator(orchestrator, config, price_book=price_book, ledger=ledger)


def test_sync_completion_records_usage_and_returns_costs() -> None:
    coordinator = _coordinator()
    result = coordinator.complete(
        [{"role": "user", "content": "hello world here now"}],
        attribution={"team": "alpha", "company": "acme"},
    )
    assert result["channel"] == "sync"
    assert result["usage"]["total_tokens"] > 0
    assert result["usage_record_id"].startswith("usage_")
    records = coordinator.ledger.records()
    assert len(records) == len(result["usage_record_ids"])
    assert all(record["team_name"] == "alpha" for record in records)
    assert all(record["provider_name"] == "mock" for record in records)
    assert all(record["model_name"] == "mock-a" for record in records)
    assert all(record["request_channel"] == "sync" for record in records)
    assert all(record["measurement_status"] == "estimated" for record in records)


def test_sync_completion_preserves_provider_reported_usage() -> None:
    """A plain provider call records measured tokens when the trace reports them."""
    coordinator = _coordinator()
    coordinator.orchestrator.client.take_usage = lambda: {
        "prompt_tokens": 7,
        "completion_tokens": 3,
    }

    result = coordinator.complete(
        [{"role": "user", "content": "measure this call"}], mode="route"
    )

    record = coordinator.ledger.records()[0]
    assert result["usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
    }
    assert result["cost"]["measurement_status"] == "measured"
    assert record["measurement_status"] == "measured"


def test_conducted_plain_completion_records_every_step_usage() -> None:
    """A conducted run preserves measured and estimated evidence per provider call."""
    coordinator = _coordinator()
    coordinator.orchestrator.run = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "workflow_run_id": "run_plain_conducted",
        "mode": "conduct",
        "answer": "final answer",
        "trace": [
            {
                "agent_id": "mock_worker",
                "output": "reported evidence",
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
            {"agent_id": "mock_worker", "output": "unreported synthesis"},
        ],
    }
    messages = [{"role": "user", "content": "conduct this request"}]

    result = coordinator.complete(messages, mode="conduct")

    records = coordinator.ledger.records()
    assert len(records) == 2
    assert result["usage_record_ids"] == [row["usage_record_id"] for row in records]
    assert result["usage_record_id"] == records[-1]["usage_record_id"]
    assert [row["measurement_status"] for row in records] == ["measured", "estimated"]
    assert result["cost"]["measurement_status"] == "estimated"
    assert result["usage"] == {
        "prompt_tokens": sum(row["prompt_tokens"] for row in records),
        "completion_tokens": sum(row["completion_tokens"] for row in records),
        "total_tokens": sum(row["total_tokens"] for row in records),
    }
    assert records[0]["prompt_tokens"] == 7
    assert records[0]["completion_tokens"] == 3
    assert records[1]["prompt_tokens"] == coordinator.token_counter.count_messages(
        messages, "mock-a"
    )


def test_sync_records_derive_provider_and_model_from_served_agent() -> None:
    coordinator = _coordinator()
    coordinator.complete([{"role": "user", "content": "do a thing"}])
    row = coordinator.ledger.records()[0]
    # cost = prompt/1k * 1 + completion/1k * 2, both > 0 given the mock echo answer
    assert row["cost_amount"] >= 0.0
    assert row["upstream_api"] == "mock"


def test_structured_provider_workflow_records_each_reported_call() -> None:
    """Evidence and final synthesis usage share one auditable run lineage."""
    coordinator = _coordinator()
    coordinator.orchestrator.client.take_usage = lambda: {
        "prompt_tokens": 2,
        "completion_tokens": 1,
    }
    result = coordinator.complete(
        [{"role": "user", "content": "return JSON"}],
        provider_request={
            "model": "mock-a",
            "messages": [{"role": "user", "content": "return JSON"}],
            "response_format": {"type": "json_object"},
        },
    )

    records = coordinator.ledger.records()
    assert result["orchestration"]["workflow_run_id"]
    assert len(result["usage_record_ids"]) == len(records) > 1
    assert {record["workflow_run_id"] for record in records} == {
        result["orchestration"]["workflow_run_id"]
    }


def test_structured_provider_workflow_estimates_each_unreported_call() -> None:
    """Mixed usage bills each measured call plus one fallback prompt estimate."""
    coordinator = _coordinator()
    calls = iter(
        [
            {"prompt_tokens": 2, "completion_tokens": 1},
            None,
            {"prompt_tokens": 3, "completion_tokens": 2},
            None,
        ]
    )
    coordinator.orchestrator.client.take_usage = lambda: next(calls, None)

    result = coordinator.complete(
        [{"role": "user", "content": "return mixed usage JSON"}],
        provider_request={
            "model": "mock-a",
            "messages": [{"role": "user", "content": "return mixed usage JSON"}],
            "response_format": {"type": "json_object"},
        },
    )

    trace = coordinator.orchestrator.get_workflow_run(
        result["orchestration"]["workflow_run_id"]
    )["trace"]
    records = coordinator.ledger.records()
    assert len(result["usage_record_ids"]) == len(records) == len(trace)
    statuses = [record["measurement_status"] for record in records]
    assert statuses.count("estimated") == 2
    assert set(statuses) == {"measured", "estimated"}
    assert result["cost"]["measurement_status"] == "estimated"
    assert records[1]["total_tokens"] > 0
    assert records[3]["total_tokens"] > 0
    request_prompt = coordinator.token_counter.count_messages(
        [{"role": "user", "content": "return mixed usage JSON"}], "mock-a"
    )
    assert sum(record["prompt_tokens"] for record in records) == request_prompt + 5
    assert [
        record["prompt_tokens"]
        for record in records
        if record["measurement_status"] == "measured"
    ] == [2, 3, 0]
    estimated = [
        record for record in records if record["measurement_status"] == "estimated"
    ]
    assert [record["prompt_tokens"] for record in estimated] == [request_prompt, 0]


def test_unreported_provider_calls_bill_request_prompt_once() -> None:
    """One completion attributes its request prompt once, not once per unreported call."""
    coordinator = _coordinator()
    coordinator.orchestrator.client.take_usage = lambda: None

    messages = [{"role": "user", "content": "return mixed usage JSON"}]
    coordinator.complete(
        messages,
        provider_request={
            "model": "mock-a",
            "messages": messages,
            "response_format": {"type": "json_object"},
        },
    )

    records = coordinator.ledger.records()
    unreported = [
        record for record in records if record["measurement_status"] == "estimated"
    ]
    assert len(unreported) >= 2
    request_prompt = coordinator.token_counter.count_messages(messages, "mock-a")
    # The full request prompt lands on the first unreported step only; later
    # unreported steps estimate just their own output tokens.
    assert sum(record["prompt_tokens"] for record in unreported) == request_prompt
    assert unreported[0]["prompt_tokens"] == request_prompt
    assert all(record["prompt_tokens"] == 0 for record in unreported[1:])


def test_structured_mixed_currency_costs_are_never_implicitly_converted() -> None:
    """Mixed currencies expose components and require an approved conversion."""
    agents = [
        ModelAgent("usd_agent", "usd-model", provider_name="usd_provider"),
        ModelAgent("eur_agent", "eur-model", provider_name="eur_provider"),
    ]
    orchestrator = TaskOrchestrator(agents)
    orchestrator.proxy_completion = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "orchestration": {"workflow_run_id": "run_mixed_currency"}
    }
    orchestrator.get_workflow_run = lambda unused_id: {  # type: ignore[method-assign]
        "workflow_run_id": "run_mixed_currency",
        "mode": "conduct",
        "trace": [
            {
                "agent_id": "usd_agent",
                "output": "usd",
                "usage": {"prompt_tokens": 1000, "completion_tokens": 0},
            },
            {
                "agent_id": "eur_agent",
                "output": "eur",
                "usage": {"prompt_tokens": 1000, "completion_tokens": 0},
            },
        ],
    }
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("usd_provider", "usd-model", 1.0, 1.0, "USD"))
    price_book.set_price(PriceEntry("eur_provider", "eur-model", 2.0, 2.0, "EUR"))
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)

    result = coordinator.complete(
        [{"role": "user", "content": "mixed currencies"}],
        provider_request={
            "model": "contextual-orchestrator",
            "messages": [{"role": "user", "content": "mixed currencies"}],
            "response_format": {"type": "json_object"},
        },
    )

    assert result["cost"]["cost_amount"] is None
    assert result["cost"]["currency_code"] == "MIXED"
    assert result["cost"]["currency_components"] == [
        {"currency_code": "EUR", "cost_amount": 2.0},
        {"currency_code": "USD", "cost_amount": 1.0},
    ]
    assert "approved exchange-rate source" in result["cost"]["customer_action"]


def test_sync_completion_survives_usage_persistence_failure() -> None:
    sink = InMemoryUsageTelemetrySink()
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("mock", "mock-a", prompt_price_per_1k=1.0, completion_price_per_1k=2.0))
    ledger = CostLedger(
        price_book,
        store=NonBlockingLedgerStore(
            _FailingLedgerStore(),
            telemetry_sink=sink,
        ),
    )
    coordinator = _coordinator(ledger=ledger)

    result = coordinator.complete([{"role": "user", "content": "hello without blocking"}])
    assert result["channel"] == "sync"
    assert result["usage_record_id"].startswith("usage_")
    assert result["usage"]["total_tokens"] > 0

    assert ledger.flush(timeout=1.0)
    assert ledger.telemetry_health()["store_failures"] == len(result["usage_record_ids"])
    assert any(
        event.attributes["contextual_orchestrator.usage.export_state"] == "export_error"
        for event in sink.events()
    )


def test_batch_completion_records_on_retrieve() -> None:
    coordinator = _coordinator()
    submitted = coordinator.complete(
        [{"role": "user", "content": "bulk job please"}],
        hints={"latency_tolerant": True},
        attribution={"team": "beta", "company": "acme"},
    )
    assert submitted["channel"] == "batch"
    # nothing recorded until results are retrieved
    assert len(coordinator.ledger.records()) == 0

    retrieved = coordinator.retrieve_batch(submitted["job_id"])
    assert retrieved["result_count"] == 1
    records = coordinator.ledger.records()
    assert len(records) == 1
    assert records[0]["request_channel"] == "batch"
    assert records[0]["team_name"] == "beta"


def test_default_local_batch_backend_reuses_orchestrator_concurrency() -> None:
    class _Client:
        local_concurrency = 3

    class _Orchestrator:
        client = _Client()

        def complete(self, messages, *, mode, model_name):
            return {"answer": messages[-1]["content"], "mode": mode}

    coordinator = CostRoutingCoordinator(_Orchestrator())

    assert coordinator.batch_backend.max_concurrency == 3


def test_cost_report_rolls_up_across_sync_and_batch() -> None:
    coordinator = _coordinator()
    sync = coordinator.complete(
        [{"role": "user", "content": "sync one"}], attribution={"company": "acme"}
    )
    job = coordinator.complete([{"role": "user", "content": "batch one"}],
                               hints={"channel": "batch"}, attribution={"company": "acme"})
    coordinator.retrieve_batch(job["job_id"])

    report = coordinator.cost_report("company")
    assert report["grand_total"]["record_count"] == len(sync["usage_record_ids"]) + 1
    assert report["items"][0]["dimension_value"] == "acme"


def test_batch_backend_can_be_pg_llm_batch() -> None:
    """The coordinator drives the injected pg-llm-batch backend for batch routing."""

    # A payload assembler that captures the JSONL lines pg-llm-batch would
    # persist, so the fake gateway can echo the same custom_ids back (as the
    # real Batch API does) — proving attribution round-trips through batch.
    captured: dict = {"lines": []}

    class _CapturingAssembler:
        def assemble(self, lines):
            captured["lines"] = lines
            return "memory://captured"

    class _FakeClient:
        async def upload_jsonl(self, file_path, endpoint_alias, purpose="batch"):
            return {"id": "file-1"}

        async def create_batch_job(self, input_file_id, endpoint_alias, endpoint="/v1/chat/completions", metadata=None):
            return {"id": "batch-1", "status": "validating"}

        async def get_batch_status(self, batch_id, endpoint_alias):
            return {"status": "completed", "is_complete": True}

        async def download_results(self, batch_id, endpoint_alias):
            return {
                "success": True,
                "responses": [{
                    "custom_id": line["custom_id"],
                    "response": {"body": {
                        "choices": [{"message": {"content": "ok"}}],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
                    }},
                } for line in captured["lines"]],
            }

    agents = [ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a", provider_name="mock",
                         tags=("reasoning",), priority=1)]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    # Batch requests carry the gateway model name; a provider-wildcard price
    # covers whichever upstream model pg-llm-batch resolves.
    price_book.set_price(PriceEntry("mock", "*", 1.0, 2.0))
    backend = PgLlmBatchBackend(_FakeClient(), endpoint_alias="gw", payload_assembler=_CapturingAssembler())
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book, batch_backend=backend)

    submitted = coordinator.complete([{"role": "user", "content": "route to pg-llm-batch"}],
                                     hints={"channel": "batch"}, attribution={"provider": "mock"})
    assert submitted["backend"] == "pg-llm-batch"
    retrieved = coordinator.retrieve_batch(submitted["job_id"])
    assert retrieved["backend"] == "pg-llm-batch"
    assert retrieved["result_count"] == 1
    row = coordinator.ledger.records()[0]
    # cost from pg-provided usage: 5/1k*1 + 5/1k*2 = 0.005 + 0.010 = 0.015
    assert row["cost_amount"] == 0.015
    assert row["request_channel"] == "batch"


if __name__ == "__main__":  # pragma: no cover
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
    print("ok")
