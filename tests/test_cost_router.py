"""Cost-routing coordinator: records usage on every sync + batch completion."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

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
    assert len(records) == 1
    assert records[0]["team_name"] == "alpha"
    assert records[0]["provider_name"] == "mock"
    assert records[0]["model_name"] == "mock-a"
    assert records[0]["request_channel"] == "sync"


def test_sync_records_derive_provider_and_model_from_served_agent() -> None:
    coordinator = _coordinator()
    coordinator.complete([{"role": "user", "content": "do a thing"}])
    row = coordinator.ledger.records()[0]
    # cost = prompt/1k * 1 + completion/1k * 2, both > 0 given the mock echo answer
    assert row["cost_amount"] >= 0.0
    assert row["upstream_api"] == "mock"


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
    assert ledger.telemetry_health()["store_failures"] == 1
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


def test_structured_output_forces_sync_when_batch_is_selected() -> None:
    coordinator = _coordinator()
    result = coordinator.complete(
        [{"role": "user", "content": "return one JSON object"}],
        hints={"channel": "batch"},
        response_format={"type": "json_object"},
    )
    assert result["channel"] == "sync"
    assert result["routing_reason"].endswith("structured_output_forced_sync")


def test_provider_native_structured_output_keeps_cost_and_lineage() -> None:
    coordinator = _coordinator()
    provider_request = {
        "model": "mock-a",
        "input": "return one JSON object",
        "text": {"format": {"type": "json_object"}},
    }
    messages = [{"role": "user", "content": "return one JSON object"}]
    provider_response = {
        "object": "response",
        "output_text": "{}",
        "output": [],
        "usage": {"input_tokens": 7, "output_tokens": 11, "total_tokens": 18},
    }

    with patch.object(
        coordinator.orchestrator.client,
        "proxy_send",
        return_value=provider_response,
    ):
        result = coordinator.complete(
            messages,
            hints={"channel": "batch"},
            response_format={"type": "json_object"},
            provider_request=provider_request,
            provider_endpoint="responses",
        )

    assert result["channel"] == "sync"
    assert result["answer"] == "{}"
    assert result["provider_response"]["orchestration"]["channel"] == "sync"
    assert result["provider_response"]["orchestration"]["usage_record_id"] == result[
        "usage_record_id"
    ]
    assert result["provider_response"]["orchestration"]["usage_record_ids"] == [
        result["usage_record_id"]
    ]
    record = coordinator.ledger.records()[0]
    assert record["prompt_tokens"] == 7
    assert record["completion_tokens"] == 11


def test_provider_native_workflow_records_each_metered_provider_call() -> None:
    coordinator = _coordinator()
    provider_response = {
        "object": "response",
        "usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
        "orchestration": {"workflow_run_id": "run_metered"},
    }
    workflow_run = {
        "workflow_run_id": "run_metered",
        "mode": "conduct",
        "answer": "{}",
        "trace": [
            {
                "agent_id": "mock_worker",
                "output": "evidence",
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            },
            {
                "agent_id": "mock_worker",
                "subtask": "Provider-facing structured synthesis",
                "output": "{}",
                "usage": {"input_tokens": 5, "output_tokens": 7},
            },
        ],
        "verification": {
            "judge_agent_id": "mock_worker",
            "judge_usage": {"prompt_tokens": 1, "completion_tokens": 2},
        },
    }

    with patch.object(
        coordinator.orchestrator,
        "proxy_completion",
        return_value=provider_response,
    ), patch.object(
        coordinator.orchestrator,
        "get_workflow_run",
        return_value=workflow_run,
    ):
        result = coordinator.complete(
            [{"role": "user", "content": "return JSON"}],
            response_format={"type": "json_object"},
            provider_request={"input": "return JSON"},
            provider_endpoint="responses",
        )

    records = coordinator.ledger.records()
    assert [(row["prompt_tokens"], row["completion_tokens"]) for row in records] == [
        (2, 3),
        (1, 2),
        (5, 7),
    ]
    assert result["usage"] == {
        "prompt_tokens": 8,
        "completion_tokens": 12,
        "total_tokens": 20,
    }
    assert result["cost"] == {"cost_amount": 0.032, "currency_code": "USD"}
    assert result["usage_record_ids"] == [row["usage_record_id"] for row in records]
    assert result["usage_record_id"] == records[-1]["usage_record_id"]
    assert result["unmetered_provider_call_count"] == 0


def test_provider_native_workflow_does_not_sum_mixed_currencies() -> None:
    coordinator = _coordinator()
    judge_agent = ModelAgent(
        id="judge_worker",
        model="mock-judge",
        base_url="mock://judge",
        provider_name="mock",
    )
    coordinator.orchestrator.candidates.append(judge_agent)
    coordinator.orchestrator.agents.append(judge_agent)
    coordinator.price_book.set_price(
        PriceEntry(
            "mock",
            "mock-judge",
            prompt_price_per_1k=1.0,
            completion_price_per_1k=1.0,
            currency_code="KRW",
        )
    )
    provider_response = {
        "usage": {"input_tokens": 5, "output_tokens": 7},
        "orchestration": {"workflow_run_id": "run_mixed_currency"},
    }
    workflow_run = {
        "workflow_run_id": "run_mixed_currency",
        "mode": "conduct",
        "answer": "{}",
        "trace": [
            {
                "agent_id": "mock_worker",
                "subtask": "Provider-facing structured synthesis",
                "output": "{}",
                "usage": {"input_tokens": 5, "output_tokens": 7},
            }
        ],
        "verification": {
            "judge_agent_id": "judge_worker",
            "judge_usage": {"prompt_tokens": 1, "completion_tokens": 2},
        },
    }

    with patch.object(
        coordinator.orchestrator, "proxy_completion", return_value=provider_response
    ), patch.object(
        coordinator.orchestrator, "get_workflow_run", return_value=workflow_run
    ):
        result = coordinator.complete(
            [{"role": "user", "content": "return JSON"}],
            response_format={"type": "json_object"},
            provider_request={"input": "return JSON"},
            provider_endpoint="responses",
        )

    assert result["cost"] == {"cost_amount": None, "currency_code": "MIXED"}
    assert [row["currency_code"] for row in coordinator.ledger.records()] == ["KRW", "USD"]


def test_provider_native_completion_rejects_unknown_endpoint() -> None:
    coordinator = _coordinator()

    with pytest.raises(ValueError, match="provider_endpoint must be"):
        coordinator.complete(
            [{"role": "user", "content": "hello"}],
            provider_request={"messages": [{"role": "user", "content": "hello"}]},
            provider_endpoint="images",
        )


def test_provider_native_completion_requires_workflow_lineage() -> None:
    coordinator = _coordinator()

    with patch.object(coordinator.orchestrator, "proxy_completion", return_value={}):
        with pytest.raises(RuntimeError, match="omitted orchestration lineage"):
            coordinator.complete(
                [{"role": "user", "content": "hello"}],
                provider_request={"messages": [{"role": "user", "content": "hello"}]},
            )


def test_default_local_batch_backend_reuses_orchestrator_concurrency() -> None:
    class _Client:
        local_concurrency = 3

    class _Orchestrator:
        client = _Client()

        def complete(self, messages, *, mode):
            return {"answer": messages[-1]["content"], "mode": mode}

    coordinator = CostRoutingCoordinator(_Orchestrator())

    assert coordinator.batch_backend.max_concurrency == 3


def test_cost_report_rolls_up_across_sync_and_batch() -> None:
    coordinator = _coordinator()
    coordinator.complete([{"role": "user", "content": "sync one"}], attribution={"company": "acme"})
    job = coordinator.complete([{"role": "user", "content": "batch one"}],
                               hints={"channel": "batch"}, attribution={"company": "acme"})
    coordinator.retrieve_batch(job["job_id"])

    report = coordinator.cost_report("company")
    assert report["grand_total"]["record_count"] == 2
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
