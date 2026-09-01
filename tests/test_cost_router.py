"""Cost-routing coordinator: records usage on every sync + batch completion."""

from __future__ import annotations

import sys
import threading
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
    BatchDownloadError,
    BatchJob,
    BatchRequest,
    BatchResultItem,
    LocalBatchBackend,
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


def test_race_loser_with_unparseable_usage_is_recorded_as_unavailable() -> None:
    """A billable race-loser call with malformed usage still gets a ledger row."""
    coordinator = _coordinator()
    context = {
        "route_mode": "route",
        "attribution": {"team": "alpha"},
        "model_name": "contextual-orchestrator",
        "workflow_run_id": "run_race_unmeasurable",
        "workflow_ready": True,
        "records": [],
        "pending_usage": [],
    }
    token = coordinator._race_usage_context.set(context)
    try:
        coordinator._record_race_endpoint_usage(
            "mock_worker",
            ("duplicate", "mock_worker", None),
        )
    finally:
        coordinator._race_usage_context.reset(token)
    records = coordinator.ledger.records()
    assert len(records) == 1
    record = records[0]
    assert record["measurement_status"] == "unavailable"
    assert record["prompt_tokens"] == 0
    assert record["completion_tokens"] == 0
    assert record["provider_name"] == "mock"
    assert record["model_name"] == "mock-a"
    assert record["workflow_run_id"] == "run_race_unmeasurable"


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


def test_sync_cost_reports_unavailable_when_a_race_loser_cannot_be_measured() -> None:
    """Devin review (#955): the plain orchestrator.run() sync path's own cost
    aggregation needs the same unavailable-outranks-estimated precedence as
    the provider_request path -- a measured winner plus an unavailable race
    loser must not report a confident "measured" total or sum a real cost
    over an unknown one.
    """
    coordinator = _coordinator()

    def run(*_args, **_kwargs):
        coordinator.orchestrator._race_usage_sink(
            "mock_worker",
            ("duplicate", "mock_worker", None),  # unparseable usage
        )
        return {
            "workflow_run_id": "run_race_unavailable",
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

    assert result["cost"]["measurement_status"] == "unavailable"
    assert result["cost"]["cost_amount"] is None
    assert "currency_components" not in result["cost"]
    assert {record["measurement_status"] for record in coordinator.ledger.records()} == {
        "measured",
        "unavailable",
    }


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


def test_structured_cost_reports_unavailable_when_a_race_loser_cannot_be_measured() -> None:
    """Devin review (#955): a measured winner plus an unavailable race loser
    must not roll up into a confident "measured" total -- the aggregate cost
    status and amount need the same honesty precedence record_stream_usage
    already applies, not just the raw per-record ledger label.
    """
    coordinator = _coordinator()

    def proxy_completion(*_args, **_kwargs):
        coordinator.orchestrator._race_usage_sink(
            "mock_worker",
            ("duplicate", "mock_worker", None),  # unparseable usage
        )
        return {
            "model": "mock-a",
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            "orchestration": {"workflow_run_id": "run_unavailable_loser"},
        }

    coordinator.orchestrator.proxy_completion = proxy_completion  # type: ignore[method-assign]
    coordinator.orchestrator.get_workflow_run = lambda _run_id: {  # type: ignore[method-assign]
        "workflow_run_id": "run_unavailable_loser",
        "mode": "route",
        "answer": "winner",
        "trace": None,
    }
    result = coordinator.complete(
        [{"role": "user", "content": "race unavailable"}],
        provider_request={
            "model": "mock-a",
            "messages": [{"role": "user", "content": "race unavailable"}],
            "response_format": {"type": "json_object"},
        },
    )

    assert result["cost"]["measurement_status"] == "unavailable"
    assert result["cost"]["cost_amount"] is None
    assert "currency_components" not in result["cost"]
    records = coordinator.ledger.records()
    assert {record["measurement_status"] for record in records} == {"measured", "unavailable"}


@pytest.mark.parametrize("structured", [False, True])
def test_unavailable_mixed_currency_cost_suppresses_partial_components(
    structured: bool,
) -> None:
    """Unknown loser spend must not expose complete-looking currency subtotals."""
    agents = [
        ModelAgent("winner_agent", "winner-model", provider_name="winner_provider"),
        ModelAgent("loser_agent", "loser-model", provider_name="loser_provider"),
    ]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("winner_provider", "winner-model", 1, 1, "USD"))
    price_book.set_price(PriceEntry("loser_provider", "loser-model", 1, 1, "EUR"))
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)

    def workflow():
        return {
            "workflow_run_id": "run_mixed_unavailable",
            "mode": "route",
            "answer": "winner",
            "trace": [{
                "agent_id": "winner_agent",
                "output": "winner",
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            }],
        }

    def emit_loser():
        orchestrator._race_usage_sink(
            "loser_agent", ("duplicate", "loser_agent", None)
        )

    if structured:
        def proxy_completion(*_args, **_kwargs):
            emit_loser()
            return {"orchestration": {"workflow_run_id": "run_mixed_unavailable"}}
        orchestrator.proxy_completion = proxy_completion  # type: ignore[method-assign]
        orchestrator.get_workflow_run = lambda _run_id: workflow()  # type: ignore[method-assign]
        result = coordinator.complete(
            [{"role": "user", "content": "mixed"}],
            provider_request={"model": "winner-model", "messages": []},
        )
    else:
        def run(*_args, **_kwargs):
            emit_loser()
            return workflow()
        orchestrator.run = run  # type: ignore[method-assign]
        result = coordinator.complete([{"role": "user", "content": "mixed"}])

    assert result["cost"] == {
        "cost_amount": None,
        "currency_code": "MIXED",
        "price_known": True,
        "measurement_status": "unavailable",
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
        {"currency_code": "EUR", "cost_amount": 2.0, "price_known": True},
        {"currency_code": "USD", "cost_amount": 1.0, "price_known": True},
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
    prompt = "bulk job please"
    submitted = coordinator.complete(
        [{"role": "user", "content": prompt}],
        hints={"latency_tolerant": True},
        attribution={"team": "beta", "company": "acme"},
    )
    assert submitted["channel"] == "batch"
    # nothing recorded until results are retrieved
    assert len(coordinator.ledger.records()) == 0

    retrieved = coordinator.retrieve_batch(submitted["job_id"])
    assert retrieved["result_count"] == 1
    records = coordinator.ledger.records()
    assert records
    assert all(record["request_channel"] == "batch" for record in records)
    assert all(record["team_name"] == "beta" for record in records)

    # The mock runner behind LocalBatchBackend reports no real per-step usage,
    # so this legitimately falls back to an estimate -- but it must be an
    # honest estimate of the *real* prompt threaded through
    # BatchResultItem.messages, not the old hardcoded blank placeholder
    # (which always computed exactly ``count_messages([{"content": ""}])``
    # tokens regardless of how long the actual prompt was).
    result = retrieved["results"][0]
    blank_prompt_tokens = coordinator.token_counter.count_messages(
        [{"role": "user", "content": ""}]
    )
    real_prompt_tokens = coordinator.token_counter.count_messages(
        [{"role": "user", "content": prompt}]
    )
    assert result["measurement_status"] == "estimated"
    assert result["prompt_tokens"] == real_prompt_tokens
    assert result["prompt_tokens"] != blank_prompt_tokens
    assert result["completion_tokens"] > 0


def test_local_batch_records_each_served_provider_at_its_own_price() -> None:
    agents = [
        ModelAgent(id="worker_a", model="model-a", base_url="mock://a", provider_name="alpha"),
        ModelAgent(id="worker_b", model="model-b", base_url="mock://b", provider_name="beta"),
    ]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("alpha", "model-a", 1.0, 2.0))
    price_book.set_price(PriceEntry("beta", "model-b", 3.0, 4.0))
    backend = LocalBatchBackend(
        lambda *_: {
            "answer": "done",
            "mode": "conduct",
            "trace": [
                {"agent_id": "worker_a", "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
                {"agent_id": "worker_b", "usage": {"prompt_tokens": 7, "completion_tokens": 3}},
            ],
        }
    )
    coordinator = CostRoutingCoordinator(
        orchestrator, config, price_book=price_book, batch_backend=backend
    )

    submitted = coordinator.complete(
        [{"role": "user", "content": "meter both"}], hints={"channel": "batch"}
    )
    result = coordinator.retrieve_batch(submitted["job_id"])["results"][0]
    rows = coordinator.ledger.records()

    assert [(row["provider_name"], row["model_name"]) for row in rows] == [
        ("alpha", "model-a"),
        ("beta", "model-b"),
    ]
    assert result["usage_record_ids"] == [row["usage_record_id"] for row in rows]
    assert result["prompt_tokens"] == 17
    assert result["completion_tokens"] == 8
    assert result["cost_amount"] == 0.053
    assert result["measurement_status"] == "measured"


def test_local_batch_malformed_usage_falls_back_without_coercion() -> None:
    coordinator = _coordinator()
    coordinator.batch_backend = LocalBatchBackend(
        lambda *_: {
            "answer": "done",
            "trace": [
                {
                    "agent_id": "mock_worker",
                    "output": "fallback",
                    "usage": {"prompt_tokens": None, "completion_tokens": 3},
                },
                {
                    "agent_id": "mock_worker",
                    "output": "again",
                    "usage": {"prompt_tokens": "7", "completion_tokens": "3"},
                },
            ],
        }
    )

    submitted = coordinator.complete(
        [{"role": "user", "content": "do not coerce"}], hints={"channel": "batch"}
    )
    result = coordinator.retrieve_batch(submitted["job_id"])["results"][0]

    assert result["measurement_status"] == "estimated"
    assert all(
        row["measurement_status"] == "estimated"
        for row in coordinator.ledger.records()
    )


def test_custom_batch_backend_preserves_one_sided_zero_usage() -> None:
    class _Backend:
        name = "custom"
        def submit(self, requests, metadata=None):
            return BatchJob("custom-zero", self.name, request_count=len(requests))
        def retrieve(self, job):
            return [BatchResultItem("request-zero", "answer", 0, 5)]
    coordinator = _coordinator()
    coordinator.batch_backend = _Backend()
    job = coordinator.complete([{"role": "user", "content": "zero prompt"}],
                               hints={"channel": "batch"})
    result = coordinator.retrieve_batch(job["job_id"])["results"][0]
    assert result["measurement_status"] == "measured"
    assert (result["prompt_tokens"], result["completion_tokens"]) == (0, 5)


def test_custom_batch_backend_rejects_negative_reported_usage() -> None:
    class _Backend:
        name = "custom"
        def submit(self, requests, metadata=None):
            return BatchJob("custom-negative", self.name, request_count=len(requests))
        def retrieve(self, job):
            return [BatchResultItem(
                "request-negative", "answer", -1, 5, usage_valid=True,
                messages=[{"role": "user", "content": "real prompt"}],
            )]
    coordinator = _coordinator()
    coordinator.batch_backend = _Backend()
    job = coordinator.complete(
        [{"role": "user", "content": "real prompt"}], hints={"channel": "batch"}
    )

    result = coordinator.retrieve_batch(job["job_id"])["results"][0]

    assert result["measurement_status"] == "estimated"
    assert result["prompt_tokens"] >= 0
    assert result["completion_tokens"] >= 0


def test_multi_item_batch_settlement_queries_ledger_once(monkeypatch) -> None:
    class _Backend:
        name = "custom"
        def submit(self, requests, metadata=None):
            return BatchJob("custom-multi", self.name, request_count=len(requests))
        def retrieve(self, job):
            return [
                BatchResultItem("request-one", "one", 1, 1),
                BatchResultItem("request-two", "two", 2, 2),
            ]
    coordinator = _coordinator()
    coordinator.batch_backend = _Backend()
    calls = 0
    records = coordinator.ledger.records

    def counted_records(*args, **kwargs):
        nonlocal calls
        calls += 1
        return records(*args, **kwargs)

    monkeypatch.setattr(coordinator.ledger, "records", counted_records)
    job = coordinator.submit_batch([
        BatchRequest("request-one", [{"role": "user", "content": "one"}]),
        BatchRequest("request-two", [{"role": "user", "content": "two"}]),
    ])

    document = coordinator.retrieve_batch(job.job_id)

    assert document["result_count"] == 2
    assert document["usage_persistence_status"] == "settled"
    assert calls == 1


def test_batch_retrieval_does_not_wait_forever_for_ledger_storage(monkeypatch) -> None:
    release = threading.Event()

    class _BlockedStore:
        def __init__(self):
            self.rows = []
        def append(self, record):
            release.wait(timeout=2)
            self.rows.append(record.as_dict())
        def query(self, start=None, end=None):
            return list(self.rows)

    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    ledger = CostLedger(
        price_book,
        store=NonBlockingLedgerStore(_BlockedStore()),
    )
    coordinator = _coordinator(ledger=ledger)
    monkeypatch.setattr(
        "contextual_orchestrator.cost_router._BATCH_LEDGER_SETTLEMENT_TIMEOUT_SECONDS",
        0.01,
    )
    job = coordinator.complete(
        [{"role": "user", "content": "blocked ledger"}], hints={"channel": "batch"}
    )
    try:
        document = coordinator.retrieve_batch(job["job_id"])
    finally:
        release.set()

    assert document["usage_persistence_status"] == "pending"
    assert document["result_count"] == 1
    assert document["results"][0]["measurement_status"] == "estimated"
    assert ledger.flush(timeout=1.0)
    settled = coordinator.retrieve_batch(job["job_id"])
    assert settled["usage_persistence_status"] == "settled"
    assert settled["results"] == document["results"]


def test_batch_settlement_ignores_unrelated_global_flush_work(monkeypatch) -> None:
    release = threading.Event()
    unrelated_started = threading.Event()

    class _Store:
        def __init__(self):
            self.rows = []
        def append(self, record):
            self.rows.append(record.as_dict())
            if record.usage_record_id == "usage_unrelated":
                unrelated_started.set()
                release.wait(timeout=2)
        def query(self, start=None, end=None):
            return list(self.rows)
        def existing_usage_record_ids(self, usage_record_ids):
            return {row["usage_record_id"] for row in self.rows
                    if row["usage_record_id"] in usage_record_ids}

    ledger = CostLedger(PriceBook(InMemoryConfigStore()),
                        store=NonBlockingLedgerStore(_Store()))
    coordinator = _coordinator(ledger=ledger)
    wait_for_ids = ledger.wait_for_usage_record_ids
    def wait_with_unrelated_work(usage_record_ids, *, timeout=None):
        ledger.record_usage(provider="mock", model="mock", prompt_tokens=1,
                            completion_tokens=1, usage_record_id="usage_unrelated")
        assert unrelated_started.wait(timeout=1)
        return wait_for_ids(usage_record_ids, timeout=timeout)
    monkeypatch.setattr(ledger, "wait_for_usage_record_ids", wait_with_unrelated_work)
    job = coordinator.complete([{"role": "user", "content": "batch settlement"}],
                               hints={"channel": "batch"})
    try:
        document = coordinator.retrieve_batch(job["job_id"])
    finally:
        release.set()
    assert document["usage_persistence_status"] == "settled"


def test_rejected_async_batch_write_remains_pending_and_idempotent(monkeypatch) -> None:
    class _RejectingStore:
        def append(self, record):
            return False
        def query(self, start=None, end=None):
            return []
        def existing_usage_record_ids(self, usage_record_ids):
            return set()

    ledger = CostLedger(PriceBook(InMemoryConfigStore()),
                        store=NonBlockingLedgerStore(_RejectingStore()))
    coordinator = _coordinator(ledger=ledger)
    monkeypatch.setattr(
        "contextual_orchestrator.cost_router._BATCH_LEDGER_SETTLEMENT_TIMEOUT_SECONDS", 0.01
    )
    job = coordinator.complete([{"role": "user", "content": "rejected write"}],
                               hints={"channel": "batch"})
    first = coordinator.retrieve_batch(job["job_id"])
    second = coordinator.retrieve_batch(job["job_id"])
    assert first["usage_persistence_status"] == "pending"
    assert second["usage_persistence_status"] == "pending"
    assert second["results"][0]["usage_record_ids"] == first["results"][0]["usage_record_ids"]
    assert ledger.records() == []


def test_local_batch_cache_hit_does_not_rebill_provider() -> None:
    coordinator = _coordinator()
    coordinator.batch_backend = LocalBatchBackend(lambda *_: {
        "answer": "cached", "cache_status": "hit",
        "trace": [{"agent_id": "mock_worker", "usage": {
            "prompt_tokens": 20, "completion_tokens": 10}}],
    })
    job = coordinator.complete([{"role": "user", "content": "cached"}],
                               hints={"channel": "batch"})
    result = coordinator.retrieve_batch(job["job_id"])["results"][0]
    assert (result["prompt_tokens"], result["completion_tokens"], result["cost_amount"]) == (0, 0, 0)
    assert [(row["provider_name"], row["request_channel"])
            for row in coordinator.ledger.records()] == [("cache", "cache")]


def test_local_batch_records_race_loser_once_across_retrievals() -> None:
    coordinator = _coordinator()
    def raced_complete(*_args, **_kwargs):
        coordinator.orchestrator._race_usage_sink(
            "mock_worker", ("loser", "mock_worker", {
                "prompt_tokens": 2, "completion_tokens": 3}))
        return {"answer": "winner", "trace": [{"agent_id": "mock_worker", "usage": {
            "prompt_tokens": 5, "completion_tokens": 7}}]}
    coordinator.orchestrator.complete = raced_complete
    job = coordinator.complete([{"role": "user", "content": "race"}],
                               hints={"channel": "batch"})
    first = coordinator.retrieve_batch(job["job_id"])
    assert first == coordinator.retrieve_batch(job["job_id"])
    assert (first["results"][0]["prompt_tokens"],
            first["results"][0]["completion_tokens"]) == (7, 10)
    assert len(coordinator.ledger.records()) == 2


def test_pg_batch_malformed_usage_estimates_real_prompt() -> None:
    captured = {}
    class _Assembler:
        def assemble(self, lines):
            captured["lines"] = lines
            return "memory://captured"
    class _Client:
        async def upload_jsonl(self, *_args):
            return {"id": "file-1"}
        async def create_batch_job(self, *_args, **_kwargs):
            return {"id": "batch-malformed", "status": "completed"}
        async def download_results(self, *_args):
            return {"success": True, "responses": [{
                "custom_id": captured["lines"][0]["custom_id"],
                "response": {"body": {
                    "choices": [{"message": {"content": "answer"}}],
                    "usage": {"prompt_tokens": "9", "completion_tokens": None},
                }},
            }]}
    coordinator = _coordinator()
    coordinator.batch_backend = PgLlmBatchBackend(_Client(), payload_assembler=_Assembler())
    messages = [{"role": "user", "content": "the real remote prompt"}]
    job = coordinator.complete(messages, hints={"channel": "batch"})
    result = coordinator.retrieve_batch(job["job_id"])["results"][0]
    assert result["measurement_status"] == "estimated"
    assert result["prompt_tokens"] == coordinator.token_counter.count_messages(
        messages, "contextual-orchestrator")


def test_batch_mixed_currency_and_retrieval_idempotency() -> None:
    agents = [
        ModelAgent("worker_alpha", "model-a", "mock://a", provider_name="alpha"),
        ModelAgent("worker_beta", "model-b", "mock://b", provider_name="beta"),
    ]
    config = InMemoryConfigStore()
    prices = PriceBook(config)
    prices.set_price(PriceEntry("alpha", "model-a", 1, 1, currency_code="USD"))
    prices.set_price(PriceEntry("beta", "model-b", 1, 1, currency_code="EUR"))
    coordinator = CostRoutingCoordinator(TaskOrchestrator(agents), config,
        price_book=prices, batch_backend=LocalBatchBackend(lambda *_: {
            "answer": "done", "trace": [
                {"agent_id": "worker_alpha", "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
                {"agent_id": "worker_beta", "usage": {"prompt_tokens": 2, "completion_tokens": 2}},
            ]}))
    job = coordinator.complete([{"role": "user", "content": "mixed"}],
                               hints={"channel": "batch"})
    first = coordinator.retrieve_batch(job["job_id"])
    prices.set_price(PriceEntry("alpha", "model-a", 99, 99, currency_code="USD"))
    prices.set_price(PriceEntry("beta", "model-b", 99, 99, currency_code="EUR"))
    assert first == coordinator.retrieve_batch(job["job_id"])
    assert [part["currency_code"] for part in
            first["results"][0]["currency_components"]] == ["EUR", "USD"]
    assert len(coordinator.ledger.records()) == 2


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
    batch = coordinator.retrieve_batch(job["job_id"])

    report = coordinator.cost_report("company")
    assert report["grand_total"]["record_count"] == (
        len(sync["usage_record_ids"]) + len(batch["results"][0]["usage_record_ids"])
    )
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


def test_retrieve_batch_propagates_download_failure_instead_of_fake_empty_success() -> None:
    """An explicit download failure must never be reported as a zero-result success.

    Regression for the bug where ``PgLlmBatchBackend.retrieve()`` mapped
    ``success: False`` to ``[]``, which ``retrieve_batch()`` then returned as
    an ordinary ``result_count: 0`` success -- indistinguishable from a batch
    that legitimately completed with nothing to report.
    """

    class _FailingClient:
        async def upload_jsonl(self, file_path, endpoint_alias, purpose="batch"):
            return {"id": "file-1"}

        async def create_batch_job(self, input_file_id, endpoint_alias, endpoint="/v1/chat/completions", metadata=None):
            return {"id": "batch-failed", "status": "validating"}

        async def get_batch_status(self, batch_id, endpoint_alias):
            return {"status": "completed", "is_complete": True}

        async def download_results(self, batch_id, endpoint_alias):
            return {"success": False, "reason": "Batch not complete"}

    agents = [ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a", provider_name="mock",
                         tags=("reasoning",), priority=1)]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("mock", "*", 1.0, 2.0))
    backend = PgLlmBatchBackend(_FailingClient())
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book, batch_backend=backend)

    submitted = coordinator.complete([{"role": "user", "content": "route to pg-llm-batch"}],
                                     hints={"channel": "batch"}, attribution={"provider": "mock"})
    with pytest.raises(BatchDownloadError) as excinfo:
        coordinator.retrieve_batch(submitted["job_id"])
    assert excinfo.value.job_id == submitted["job_id"]
    assert excinfo.value.reason == "Batch not complete"
    # No usage was recorded for the failed retrieval.
    assert coordinator.ledger.records() == []


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


def test_embedding_batch_selects_cheapest_capability_candidate_when_unspecified() -> None:
    """Price-aware selection: an unspecified member picks price, not rank order.

    ``ranked_first`` outranks ``cheaper`` under the orchestrator's own
    priority-based ordering (verified below), so a price-blind ``candidates[0]``
    pick would return it. The coordinator must instead resolve to the cheaper
    member via ``_cheapest_capability_candidate``'s direct
    ``PriceBook.get_price()`` lookup and raw ``prompt_price_per_1k``
    comparison (it does not call ``cheapest_upstream``).
    """
    from contextual_orchestrator.batch_routing import EmbeddingBatchResultItem

    ranked_first = ModelAgent(
        "ranked_first_zdr_member",
        "expensive-embedding",
        "mock://expensive",
        provider_name="expensive-provider",
        tags=("embedding", "privacy:zdr"),
        priority=10,
    )
    cheaper = ModelAgent(
        "cheaper_zdr_member",
        "cheap-embedding",
        "mock://cheap",
        provider_name="cheap-provider",
        tags=("embedding", "privacy:zdr"),
        priority=1,
    )

    class _RecordingEmbeddingBackend:
        name = "recording"

        def __init__(self) -> None:
            self.requests = []

        def submit(self, requests, metadata=None):
            self.requests.extend(requests)
            return BatchJob("cheapest-pick", self.name, status="completed", request_count=len(requests))

        def poll(self, job):
            return {"is_complete": True, "status": "completed"}

        def retrieve(self, job):
            return [EmbeddingBatchResultItem(request.custom_id, 0, [1.0], 1, request.model) for request in self.requests]

    backend = _RecordingEmbeddingBackend()
    orchestrator = TaskOrchestrator([ranked_first, cheaper])
    with orchestrator.request_policy(True):
        ranked = orchestrator._capability_agents("embedding", None)
    assert [agent.id for agent in ranked] == [ranked_first.id, cheaper.id]

    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(
        PriceEntry("expensive-provider", "expensive-embedding", prompt_price_per_1k=5.0, completion_price_per_1k=0.0)
    )
    price_book.set_price(
        PriceEntry("cheap-provider", "cheap-embedding", prompt_price_per_1k=0.01, completion_price_per_1k=0.0)
    )
    coordinator = CostRoutingCoordinator(
        orchestrator, config, price_book=price_book, embedding_batch_backend=backend
    )

    document = coordinator.complete_embeddings_batch(["private"], zdr_only=True)

    assert document["status"] == "completed"
    assert backend.requests[0].model == cheaper.model
    assert backend.requests[0].agent_id == cheaper.id


def test_cheapest_capability_candidate_prefers_known_price_over_unpriced() -> None:
    """An unpriced member must not win as a false zero-cost candidate.

    ``ranked_first`` outranks ``priced`` under the orchestrator's own
    priority order but carries no price-book entry at all; it must lose to
    the known, paid ``priced`` member rather than being treated as free.
    """
    ranked_first = ModelAgent(
        "ranked_first_member", "unpriced-embedding", "mock://unpriced",
        provider_name="unpriced-provider", tags=("embedding",), priority=10,
    )
    priced = ModelAgent(
        "priced_member", "paid-embedding", "mock://paid",
        provider_name="paid-provider", tags=("embedding",), priority=1,
    )
    orchestrator = TaskOrchestrator([ranked_first, priced])
    with orchestrator.request_policy(False):
        candidates = orchestrator._capability_agents("embedding", None)
    assert [agent.id for agent in candidates] == [ranked_first.id, priced.id]

    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(
        PriceEntry("paid-provider", "paid-embedding", prompt_price_per_1k=5.0, completion_price_per_1k=0.0)
    )
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)

    chosen = coordinator._cheapest_capability_candidate(candidates)

    assert chosen.id == priced.id


def test_cheapest_capability_candidate_ignores_unpriced_and_keeps_ranked_order() -> None:
    """An all-unpriced pool must preserve the pre-existing ranked order, not always pick index 0."""
    ranked_first = ModelAgent(
        "ranked_first_member", "unpriced-one", "mock://one",
        provider_name="unpriced-provider-one", tags=("embedding",), priority=10,
    )
    ranked_second = ModelAgent(
        "ranked_second_member", "unpriced-two", "mock://two",
        provider_name="unpriced-provider-two", tags=("embedding",), priority=1,
    )
    orchestrator = TaskOrchestrator([ranked_first, ranked_second])
    with orchestrator.request_policy(False):
        candidates = orchestrator._capability_agents("embedding", None)
    assert [agent.id for agent in candidates] == [ranked_first.id, ranked_second.id]

    coordinator = CostRoutingCoordinator(orchestrator, InMemoryConfigStore())

    chosen = coordinator._cheapest_capability_candidate(candidates)

    assert chosen.id == ranked_first.id


def test_cheapest_capability_candidate_ignores_mismatched_currency() -> None:
    """A different-currency price must not be compared to a default-currency price by face value.

    ``foreign_member`` has a numerically smaller price but in a currency this
    repo has no exchange rate for; it must lose to the known, comparable
    ``domestic_member`` price rather than win on raw face value.
    """
    foreign_member = ModelAgent(
        "foreign_priced_member", "foreign-embedding", "mock://foreign",
        provider_name="foreign-provider", tags=("embedding",), priority=10,
    )
    domestic_member = ModelAgent(
        "domestic_priced_member", "domestic-embedding", "mock://domestic",
        provider_name="domestic-provider", tags=("embedding",), priority=1,
    )
    orchestrator = TaskOrchestrator([foreign_member, domestic_member])
    with orchestrator.request_policy(False):
        candidates = orchestrator._capability_agents("embedding", None)

    config = InMemoryConfigStore()
    price_book = PriceBook(config)  # default_currency == "USD"
    price_book.set_price(
        PriceEntry(
            "foreign-provider", "foreign-embedding",
            prompt_price_per_1k=1.0, completion_price_per_1k=0.0, currency_code="JPY",
        )
    )
    price_book.set_price(
        PriceEntry(
            "domestic-provider", "domestic-embedding",
            prompt_price_per_1k=5.0, completion_price_per_1k=0.0, currency_code="USD",
        )
    )
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)

    chosen = coordinator._cheapest_capability_candidate(candidates)

    assert chosen.id == domestic_member.id


def test_cheapest_capability_candidate_ignores_completion_price_for_embeddings() -> None:
    """Embedding routing must not price nonexistent completion tokens.

    ``cheap_input_member`` has the lowest true (input-only) cost but a huge
    completion price that would dominate under a nonzero
    ``assumed_completion_tokens``; it must still win because embeddings never
    consume completion tokens.
    """
    cheap_input_member = ModelAgent(
        "cheap_input_member", "cheap-input-embedding", "mock://cheap-input",
        provider_name="cheap-input-provider", tags=("embedding",), priority=10,
    )
    expensive_input_member = ModelAgent(
        "expensive_input_member", "expensive-input-embedding", "mock://expensive-input",
        provider_name="expensive-input-provider", tags=("embedding",), priority=1,
    )
    orchestrator = TaskOrchestrator([cheap_input_member, expensive_input_member])
    with orchestrator.request_policy(False):
        candidates = orchestrator._capability_agents("embedding", None)

    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(
        PriceEntry(
            "cheap-input-provider", "cheap-input-embedding",
            prompt_price_per_1k=0.01, completion_price_per_1k=100.0,
        )
    )
    price_book.set_price(
        PriceEntry(
            "expensive-input-provider", "expensive-input-embedding",
            prompt_price_per_1k=1.0, completion_price_per_1k=0.0,
        )
    )
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)

    chosen = coordinator._cheapest_capability_candidate(candidates)

    assert chosen.id == cheap_input_member.id


def test_cheapest_capability_candidate_compares_equivalent_currency_spellings() -> None:
    """Lowercase/padded currency codes must still compare as the same currency.

    ``padded_lowercase_member`` has the true lowest price, but its price
    entry stores the currency as ``"  usd  "`` (lowercase, padded) rather
    than the price book's canonical ``"USD"``. An exact-string currency
    comparison would wrongly treat that as a different, non-comparable
    currency and let the costlier ``canonical_member`` win instead. This
    mirrors ``model_discovery._currency_is_comparable``'s own
    non-empty/trimmed/case-insensitive normalization.
    """
    padded_lowercase_member = ModelAgent(
        "padded_lowercase_member", "padded-embedding", "mock://padded",
        provider_name="padded-provider", tags=("embedding",), priority=10,
    )
    canonical_member = ModelAgent(
        "canonical_member", "canonical-embedding", "mock://canonical",
        provider_name="canonical-provider", tags=("embedding",), priority=1,
    )
    orchestrator = TaskOrchestrator([padded_lowercase_member, canonical_member])
    with orchestrator.request_policy(False):
        candidates = orchestrator._capability_agents("embedding", None)

    config = InMemoryConfigStore()
    price_book = PriceBook(config)  # default_currency == "USD"
    price_book.set_price(
        PriceEntry(
            "padded-provider", "padded-embedding",
            prompt_price_per_1k=0.01, completion_price_per_1k=0.0, currency_code="  usd  ",
        )
    )
    price_book.set_price(
        PriceEntry(
            "canonical-provider", "canonical-embedding",
            prompt_price_per_1k=5.0, completion_price_per_1k=0.0, currency_code="USD",
        )
    )
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)

    chosen = coordinator._cheapest_capability_candidate(candidates)

    assert chosen.id == padded_lowercase_member.id


def test_cheapest_capability_candidate_breaks_ledger_rounding_ties_on_raw_price() -> None:
    """Devin round-3 bug: tiny embedding prices must not collapse into ties.

    ``ranked_first`` (0.00000049 per 1K) and ``cheaper`` (0.00000001 per 1K)
    are genuinely different prices, but ``PriceBook.compute_cost`` quantizes
    to six decimal places for ledger reporting, so both round to the same
    ``0.0`` cost for the assumed 1,000-token request that ``cheapest_upstream``
    prices candidates against. A comparison that goes through that rounded
    cost sees a tie and keeps the ranked-first (here, pricier) candidate;
    the fix must instead compare the raw, unrounded ``prompt_price_per_1k``
    and pick the actually-cheaper member.
    """
    ranked_first = ModelAgent(
        "ranked_first_member", "tiny-expensive-embedding", "mock://tiny-expensive",
        provider_name="tiny-expensive-provider", tags=("embedding",), priority=10,
    )
    cheaper = ModelAgent(
        "cheaper_member", "tiny-cheap-embedding", "mock://tiny-cheap",
        provider_name="tiny-cheap-provider", tags=("embedding",), priority=1,
    )
    orchestrator = TaskOrchestrator([ranked_first, cheaper])
    with orchestrator.request_policy(False):
        candidates = orchestrator._capability_agents("embedding", None)
    assert [agent.id for agent in candidates] == [ranked_first.id, cheaper.id]

    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(
        PriceEntry(
            "tiny-expensive-provider", "tiny-expensive-embedding",
            prompt_price_per_1k=0.00000049, completion_price_per_1k=0.0,
        )
    )
    price_book.set_price(
        PriceEntry(
            "tiny-cheap-provider", "tiny-cheap-embedding",
            prompt_price_per_1k=0.00000001, completion_price_per_1k=0.0,
        )
    )
    # Confirm both really do collapse to the same rounded ledger cost, so
    # this test would have failed against the pre-fix rounded comparison.
    expensive_cost, *_ = price_book.compute_cost(
        "tiny-expensive-provider", "tiny-expensive-embedding", 1000, 0
    )
    cheap_cost, *_ = price_book.compute_cost(
        "tiny-cheap-provider", "tiny-cheap-embedding", 1000, 0
    )
    assert expensive_cost == cheap_cost == 0.0

    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)

    chosen = coordinator._cheapest_capability_candidate(candidates)

    assert chosen.id == cheaper.id


def test_non_zdr_embedding_batch_selects_cheapest_capability_candidate_when_unspecified() -> None:
    """Devin bug: ordinary (non-ZDR) unspecified embedding batches must also price-route.

    Previously ``_resolve_embedding_target`` returned before
    ``_cheapest_capability_candidate`` ever ran whenever ``zdr_only=False``,
    so only ZDR embedding batches were cost-aware; ordinary batches always
    kept the orchestrator's ranked (not price) order. An unspecified
    (auto/group) model with multiple differently priced non-ZDR group
    members must now resolve to the cheaper one.
    """
    from contextual_orchestrator.batch_routing import EmbeddingBatchResultItem

    ranked_first = ModelAgent(
        "ranked_first_plain_member", "expensive-plain-embedding", "mock://expensive-plain",
        provider_name="expensive-plain-provider", tags=("embedding",),
        group_name="shared_embedding_model", priority=10,
    )
    cheaper = ModelAgent(
        "cheaper_plain_member", "cheap-plain-embedding", "mock://cheap-plain",
        provider_name="cheap-plain-provider", tags=("embedding",),
        group_name="shared_embedding_model", priority=1,
    )

    class _RecordingEmbeddingBackend:
        name = "recording"

        def __init__(self) -> None:
            self.requests = []

        def submit(self, requests, metadata=None):
            self.requests.extend(requests)
            return BatchJob(
                "non-zdr-cheapest", self.name, status="completed", request_count=len(requests)
            )

        def poll(self, job):
            return {"is_complete": True, "status": "completed"}

        def retrieve(self, job):
            return [
                EmbeddingBatchResultItem(request.custom_id, 0, [1.0], 1, request.model)
                for request in self.requests
            ]

    backend = _RecordingEmbeddingBackend()
    orchestrator = TaskOrchestrator([ranked_first, cheaper])
    with orchestrator.request_policy(False):
        ranked = orchestrator._capability_agents("embedding", None)
    assert [agent.id for agent in ranked] == [ranked_first.id, cheaper.id]

    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(
        PriceEntry(
            "expensive-plain-provider", "expensive-plain-embedding",
            prompt_price_per_1k=5.0, completion_price_per_1k=0.0,
        )
    )
    price_book.set_price(
        PriceEntry(
            "cheap-plain-provider", "cheap-plain-embedding",
            prompt_price_per_1k=0.01, completion_price_per_1k=0.0,
        )
    )
    coordinator = CostRoutingCoordinator(
        orchestrator, config, price_book=price_book, embedding_batch_backend=backend
    )

    # zdr_only defaults False and agent_id defaults None: the ordinary path.
    coordinator.submit_embeddings_batch(["ordinary input"])

    assert backend.requests[0].model == cheaper.model
    assert backend.requests[0].agent_id == cheaper.id


def test_non_zdr_complete_embeddings_batch_selects_cheapest_capability_candidate() -> None:
    """Same fix, exercised through ``complete_embeddings_batch`` — the public,
    synchronous coordinator entry point production callers (e.g. naruon's
    batch embedding service) call directly."""
    ranked_first = ModelAgent(
        "ranked_first_public_member", "expensive-public-embedding", "mock://expensive-public",
        provider_name="expensive-public-provider", tags=("embedding",), priority=10,
    )
    cheaper = ModelAgent(
        "cheaper_public_member", "cheap-public-embedding", "mock://cheap-public",
        provider_name="cheap-public-provider", tags=("embedding",), priority=1,
    )
    orchestrator = TaskOrchestrator([ranked_first, cheaper])

    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(
        PriceEntry(
            "expensive-public-provider", "expensive-public-embedding",
            prompt_price_per_1k=5.0, completion_price_per_1k=0.0,
        )
    )
    price_book.set_price(
        PriceEntry(
            "cheap-public-provider", "cheap-public-embedding",
            prompt_price_per_1k=0.01, completion_price_per_1k=0.0,
        )
    )
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)

    document = coordinator.complete_embeddings_batch(["ordinary input"])

    assert document["model"] == cheaper.model


def test_non_zdr_embedding_batch_preserves_explicit_model_outside_the_pool() -> None:
    """An explicit model absent from the pool must still pass through unresolved.

    Widening ``_resolve_embedding_target`` to cost-route unspecified
    non-ZDR requests must not force *every* ordinary embedding request
    through ``_capability_agents`` — only the unspecified (auto/group
    placeholder) case should. An explicit model outside the configured pool
    has no matching agent to look up and must not raise or be rewritten.
    """
    orchestrator = TaskOrchestrator(
        [ModelAgent("configured_agent", "configured-embedding", tags=("embedding",))]
    )
    coordinator = CostRoutingCoordinator(orchestrator, InMemoryConfigStore())

    resolved_model, resolved_agent_id = coordinator._resolve_embedding_target(
        "unconfigured-upstream-model", zdr_only=False, agent_id=None
    )

    assert resolved_model == "unconfigured-upstream-model"
    assert resolved_agent_id is None


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
