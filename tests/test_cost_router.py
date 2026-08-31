"""Cost-routing coordinator: records usage on every sync + batch completion."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

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
from contextual_orchestrator.batch_routing import (  # noqa: E402
    BatchJob,
    BatchRequest,
    PgLlmBatchBackend,
)
from contextual_orchestrator.cost_router import BatchModelSelectionError  # noqa: E402


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
    assert "currency_components" not in result["cost"]
    assert record["measurement_status"] == "measured"


def test_sync_completion_scopes_zdr_policy_to_direct_run() -> None:
    coordinator = _coordinator()
    agent = coordinator.orchestrator.agents[0]
    observed: list[bool] = []

    def run(*_args, **_kwargs):
        observed.append(coordinator.orchestrator._zdr_agent_allowed(agent))
        return {
            "workflow_run_id": "run_direct_zdr",
            "mode": "route",
            "answer": "answer",
            "trace": [{"agent_id": agent.id, "output": "answer"}],
        }

    coordinator.orchestrator.run = run  # type: ignore[method-assign]
    coordinator.complete(
        [{"role": "user", "content": "private request"}],
        mode="route",
        zdr_only=True,
    )

    assert observed == [False]


def test_provider_completion_scopes_zdr_policy_to_direct_proxy() -> None:
    coordinator = _coordinator()
    agent = coordinator.orchestrator.agents[0]
    observed: list[bool] = []

    def proxy_completion(*_args, **_kwargs):
        observed.append(coordinator.orchestrator._zdr_agent_allowed(agent))
        return {
            "model": agent.model,
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "orchestration": {"workflow_run_id": "run_proxy_zdr"},
        }

    coordinator.orchestrator.proxy_completion = proxy_completion  # type: ignore[method-assign]
    coordinator.orchestrator.get_workflow_run = lambda _run_id: {  # type: ignore[method-assign]
        "workflow_run_id": "run_proxy_zdr",
        "mode": "route",
        "answer": "answer",
        "trace": [],
    }
    coordinator.complete(
        [{"role": "user", "content": "private provider request"}],
        provider_request={"model": agent.model, "messages": []},
        zdr_only=True,
    )

    assert observed == [False]


def test_sync_empty_trace_preserves_top_level_provider_usage() -> None:
    """An empty trace still records measured usage returned by the provider run."""
    coordinator = _coordinator()
    coordinator.orchestrator.run = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
        "workflow_run_id": "run_empty",
        "mode": "route",
        "answer": "measured answer",
        "trace": [],
        "usage": {"prompt_tokens": 11, "completion_tokens": 4},
    }

    result = coordinator.complete([{"role": "user", "content": "measure empty trace"}])

    record = coordinator.ledger.records()[0]
    assert result["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 4,
        "total_tokens": 15,
    }
    assert record["measurement_status"] == "measured"


def test_completed_race_loser_usage_is_recorded_as_measured_provider_spend() -> None:
    coordinator = _coordinator()
    context = {
        "route_mode": "route",
        "attribution": {"team": "alpha"},
        "model_name": "contextual-orchestrator",
        "workflow_run_id": None,
        "workflow_ready": False,
        "records": [],
        "pending_usage": [],
    }
    token = coordinator._race_usage_context.set(context)
    try:
        coordinator._record_race_endpoint_usage(
            "mock_worker",
            ("duplicate", "mock_worker", {"prompt_tokens": 5, "completion_tokens": 2}),
        )
        assert coordinator.ledger.records() == []
        context["workflow_run_id"] = "run_race"
        context["workflow_ready"] = True
        coordinator._flush_race_endpoint_usage(context)
    finally:
        coordinator._race_usage_context.reset(token)
    record = coordinator.ledger.records()[0]
    assert record["prompt_tokens"] == 5
    assert record["completion_tokens"] == 2
    assert record["measurement_status"] == "measured"
    assert record["workflow_run_id"] == "run_race"


def test_race_loser_derives_provider_from_base_url_when_name_is_absent() -> None:
    """Race-loser spend uses the same provider identity as winner accounting."""
    agent = ModelAgent(
        id="gateway_worker",
        model="gateway-model",
        base_url="https://gateway.example/v1",
        provider_name="",
        tags=("reasoning",),
    )
    orchestrator = TaskOrchestrator([agent])
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(
        PriceEntry(
            "gateway.example",
            "gateway-model",
            prompt_price_per_1k=1.0,
            completion_price_per_1k=2.0,
        )
    )
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)
    context = {
        "route_mode": "route",
        "attribution": None,
        "model_name": "contextual-orchestrator",
        "workflow_run_id": "run_gateway_race",
        "workflow_ready": True,
        "records": [],
        "pending_usage": [],
    }
    token = coordinator._race_usage_context.set(context)
    try:
        coordinator._record_race_endpoint_usage(
            "gateway_worker",
            (
                "duplicate",
                "gateway_worker",
                {"prompt_tokens": 1000, "completion_tokens": 1000},
            ),
        )
    finally:
        coordinator._race_usage_context.reset(token)

    record = coordinator.ledger.records()[0]
    assert record["provider_name"] == "gateway.example"
    assert record["upstream_api"] == "gateway.example"
    assert record["cost_amount"] == 3.0


def test_race_loser_cost_does_not_inflate_openai_completion_usage() -> None:
    coordinator = _coordinator()

    def run(*_args, **_kwargs):
        coordinator.orchestrator._race_usage_sink(
            "mock_worker",
            ("duplicate", "mock_worker", {"prompt_tokens": 5, "completion_tokens": 2}),
        )
        return {
            "workflow_run_id": "run_race_usage",
            "mode": "route",
            "answer": "winner",
            "trace": [
                {
                    "agent_id": "mock_worker",
                    "output": "winner",
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                }
            ],
        }

    coordinator.orchestrator.run = run  # type: ignore[method-assign]
    result = coordinator.complete([{"role": "user", "content": "race"}], mode="route")
    assert result["usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
    }
    assert len(coordinator.ledger.records()) == 2
    assert result["cost"]["cost_amount"] == 0.022


def test_ready_race_usage_without_workflow_id_is_not_discarded() -> None:
    coordinator = _coordinator()
    context = {
        "route_mode": "route",
        "attribution": None,
        "model_name": "contextual-orchestrator",
        "workflow_run_id": None,
        "workflow_ready": True,
        "records": [],
        "pending_usage": [],
    }
    token = coordinator._race_usage_context.set(context)
    try:
        coordinator._record_race_endpoint_usage(
            "mock_worker",
            ("duplicate", "mock_worker", {"prompt_tokens": 1, "completion_tokens": 1}),
        )
    finally:
        coordinator._race_usage_context.reset(token)
    assert len(coordinator.ledger.records()) == 1
    assert coordinator.ledger.records()[0]["workflow_run_id"] is None


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


def test_structured_empty_trace_records_winner_even_after_race_loser() -> None:
    coordinator = _coordinator()

    def proxy_completion(*_args, **_kwargs):
        coordinator.orchestrator._race_usage_sink(
            "mock_worker",
            ("duplicate", "mock_worker", {"prompt_tokens": 5, "completion_tokens": 2}),
        )
        return {
            "model": "mock-a",
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            "orchestration": {"workflow_run_id": "run_empty_trace"},
        }

    coordinator.orchestrator.proxy_completion = proxy_completion  # type: ignore[method-assign]
    coordinator.orchestrator.get_workflow_run = lambda _run_id: {  # type: ignore[method-assign]
        "workflow_run_id": "run_empty_trace",
        "mode": "route",
        "answer": "winner",
        "trace": None,
    }
    result = coordinator.complete(
        [{"role": "user", "content": "race structured"}],
        provider_request={
            "model": "mock-a",
            "messages": [{"role": "user", "content": "race structured"}],
            "response_format": {"type": "json_object"},
        },
    )
    records = coordinator.ledger.records()
    assert len(records) == 2
    assert {(row["prompt_tokens"], row["completion_tokens"]) for row in records} == {
        (5, 2),
        (7, 3),
    }
    assert len(result["usage_record_ids"]) == 2


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


def test_zdr_batch_resolves_each_request_to_a_member_of_its_configured_pool() -> None:
    non_zdr = ModelAgent(
        "non_zdr_member",
        "vendor/non-zdr",
        "mock://non-zdr",
        provider_name="vendor",
        priority=99,
        group_name="shared_reasoning_model",
    )
    zdr = ModelAgent(
        "zdr_member",
        "vendor/zdr",
        "mock://zdr",
        provider_name="vendor",
        tags=("privacy:zdr",),
        group_name="shared_reasoning_model",
    )
    orchestrator = TaskOrchestrator([non_zdr, zdr])
    captured: list[BatchRequest] = []

    class _CapturingBackend:
        name = "capturing"

        def submit(self, requests, metadata=None):
            captured.extend(requests)
            return BatchJob("batch-zdr", self.name, status="submitted", request_count=len(requests))

    coordinator = CostRoutingCoordinator(
        orchestrator,
        batch_backend=_CapturingBackend(),
    )
    coordinator.submit_batch(
        [
            BatchRequest(
                messages=[{"role": "user", "content": "private batch"}],
                model=TaskOrchestrator.AUTO_MODEL,
                zdr_only=True,
            )
        ]
    )

    assert captured[0].model == zdr.model
    assert captured[0].zdr_only is True


def test_zdr_batch_rejects_an_explicit_non_zdr_configured_model() -> None:
    non_zdr = ModelAgent(
        "non_zdr_member",
        "vendor/non-zdr",
        "mock://non-zdr",
        provider_name="vendor",
    )
    coordinator = CostRoutingCoordinator(TaskOrchestrator([non_zdr]))

    with pytest.raises(BatchModelSelectionError):
        coordinator.submit_batch(
            [
                BatchRequest(
                    messages=[{"role": "user", "content": "private batch"}],
                    model=non_zdr.model,
                    zdr_only=True,
                )
            ]
        )


def test_zdr_embedding_batch_preserves_selected_member_with_duplicate_models() -> None:
    """A retry member must not be re-resolved to the first duplicate model."""
    from contextual_orchestrator.batch_routing import EmbeddingBatchResultItem

    first = ModelAgent(
        "first_zdr_member",
        "shared-embedding",
        "mock://first",
        provider_name="first-provider",
        tags=("embedding", "privacy:zdr"),
    )
    second = ModelAgent(
        "second_zdr_member",
        "shared-embedding",
        "mock://second",
        provider_name="second-provider",
        tags=("embedding", "privacy:zdr"),
    )

    class _RecordingEmbeddingBackend:
        name = "recording"

        def __init__(self) -> None:
            self.requests = []

        def submit(self, requests, metadata=None):
            self.requests.extend(requests)
            return BatchJob("duplicate-model", self.name, status="completed", request_count=len(requests))

        def poll(self, job):
            return {"is_complete": True, "status": "completed"}

        def retrieve(self, job):
            return [EmbeddingBatchResultItem(request.custom_id, 0, [1.0], 1, request.model) for request in self.requests]

    backend = _RecordingEmbeddingBackend()
    orchestrator = TaskOrchestrator([first, second])

    def fail_reselection(*_args, **_kwargs):
        raise AssertionError("the selected embedding member must not be re-resolved")

    orchestrator.select_capability_agent = fail_reselection  # type: ignore[method-assign]
    coordinator = CostRoutingCoordinator(orchestrator, embedding_batch_backend=backend)
    document = coordinator.complete_embeddings_batch(
        ["private"], model=second.model, zdr_only=True, agent_id=second.id
    )

    assert document["status"] == "completed"
    assert backend.requests[0].model == second.model
    assert backend.requests[0].agent_id == second.id


def test_provider_embedding_runner_accepts_empty_direct_batch() -> None:
    """The provider backend's direct contract returns an empty batch without indexing it."""
    agent = ModelAgent(
        "remote_embedding",
        "synthetic-embedding",
        "https://provider.synthetic.invalid/v1",
        tags=("embedding",),
    )
    orchestrator = TaskOrchestrator([agent])
    orchestrator.client.embed = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("an empty batch must not call the provider")
    )
    coordinator = CostRoutingCoordinator(orchestrator)
    backend = coordinator.embedding_batch_backend
    job = backend.submit([])
    deadline = time.time() + 2
    while backend.poll(job)["status"] not in {"completed", "failed"} and time.time() < deadline:
        time.sleep(0.01)
    assert backend.poll(job)["status"] == "completed"
    assert backend.retrieve(job) == []


def test_non_zdr_batch_preserves_an_explicit_model_outside_the_pool() -> None:
    """The ZDR resolver must not change ordinary batch passthrough behavior."""
    captured: list[BatchRequest] = []

    class _CapturingBackend:
        name = "capturing"

        def submit(self, requests, metadata=None):
            captured.extend(requests)
            return BatchJob("batch-ordinary", self.name, status="submitted", request_count=len(requests))

    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([ModelAgent("configured_agent", "configured-model", "mock://configured")]),
        batch_backend=_CapturingBackend(),
    )
    request = BatchRequest(
        messages=[{"role": "user", "content": "ordinary batch"}],
        model="unconfigured-provider-model",
    )

    coordinator.submit_batch([request])

    assert captured == [request]


if __name__ == "__main__":  # pragma: no cover
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
    print("ok")
