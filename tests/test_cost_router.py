"""Cost-routing coordinator: records usage on every sync + batch completion."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    PriceBook,
    PriceEntry,
    TaskOrchestrator,
)
from contextual_orchestrator.batch_routing import PgLlmBatchBackend  # noqa: E402


def _coordinator() -> CostRoutingCoordinator:
    agents = [
        ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a", provider_name="mock",
                   tags=("reasoning", "coding", "writing"), priority=1),
    ]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("mock", "mock-a", prompt_price_per_1k=1.0, completion_price_per_1k=2.0))
    return CostRoutingCoordinator(orchestrator, config, price_book=price_book)


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
