"""Routing: sync-vs-batch decision, local backend, and the pg-llm-batch path (mocked)."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.batch_routing import (  # noqa: E402
    BatchRequest,
    LocalBatchBackend,
    PgLlmBatchBackend,
    RoutingHints,
    RoutingPolicy,
    build_jsonl_body,
    cheapest_upstream,
)
from contextual_orchestrator.cost_ledger import PriceBook, PriceEntry  # noqa: E402
from contextual_orchestrator.kv_config import InMemoryConfigStore  # noqa: E402


# ---------------------------------------------------------------------------
# Sync-vs-batch decision
# ---------------------------------------------------------------------------


def test_default_request_routes_sync() -> None:
    policy = RoutingPolicy(InMemoryConfigStore())
    decision = policy.decide(RoutingHints())
    assert decision.channel == "sync"


def test_latency_tolerant_routes_batch() -> None:
    policy = RoutingPolicy(InMemoryConfigStore())
    decision = policy.decide(RoutingHints(latency_tolerant=True))
    assert decision.channel == "batch"


def test_explicit_channel_hint_is_honoured() -> None:
    policy = RoutingPolicy(InMemoryConfigStore())
    assert policy.decide(RoutingHints(channel="batch")).channel == "batch"
    assert policy.decide(RoutingHints(channel="sync", latency_tolerant=True)).channel == "sync"


def test_bulk_priority_routes_batch_but_interactive_forces_sync() -> None:
    policy = RoutingPolicy(InMemoryConfigStore())
    assert policy.decide(RoutingHints(priority="bulk")).channel == "batch"
    # interactive stays sync even when latency_tolerant is set
    assert policy.decide(RoutingHints(priority="interactive", latency_tolerant=True)).channel == "sync"


def test_batch_min_tokens_threshold_from_config() -> None:
    config = InMemoryConfigStore()
    config.set("routing", "batch_min_tokens", 500)
    policy = RoutingPolicy(config)
    assert policy.decide(RoutingHints(), prompt_tokens=200).channel == "sync"
    assert policy.decide(RoutingHints(), prompt_tokens=800).channel == "batch"


def test_batch_disabled_config_forces_sync() -> None:
    config = InMemoryConfigStore()
    config.set("routing", "batch_enabled", False)
    policy = RoutingPolicy(config)
    assert policy.decide(RoutingHints(latency_tolerant=True)).channel == "sync"


# ---------------------------------------------------------------------------
# Cost-optimising upstream selection
# ---------------------------------------------------------------------------


def test_cheapest_upstream_picks_lowest_priced_candidate() -> None:
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("cheap_co", "small", prompt_price_per_1k=0.1, completion_price_per_1k=0.1))
    price_book.set_price(PriceEntry("pricey_co", "large", prompt_price_per_1k=5.0, completion_price_per_1k=10.0))
    candidates = [
        {"provider": "pricey_co", "model": "large"},
        {"provider": "cheap_co", "model": "small"},
    ]
    best = cheapest_upstream(candidates, price_book)
    assert best == {"provider": "cheap_co", "model": "small"}


# ---------------------------------------------------------------------------
# Local (mock/standalone) backend
# ---------------------------------------------------------------------------


def test_local_backend_runs_requests_in_process() -> None:
    def runner(messages, mode):
        return {"answer": f"echo:{messages[-1]['content']}", "mode": "route"}

    backend = LocalBatchBackend(runner)
    requests = [
        BatchRequest(messages=[{"role": "user", "content": "one"}], custom_id="a"),
        BatchRequest(messages=[{"role": "user", "content": "two"}], custom_id="b"),
    ]
    job = backend.submit(requests)
    assert job.request_count == 2
    assert backend.poll(job)["is_complete"] is True
    results = backend.retrieve(job)
    answers = {item.custom_id: item.answer for item in results}
    assert answers == {"a": "echo:one", "b": "echo:two"}


# ---------------------------------------------------------------------------
# pg-llm-batch backend (mocked async client mirroring BatchAPIClient)
# ---------------------------------------------------------------------------


class _FakeBatchApiClient:
    """Mimics pg_llm_batch.BatchAPIClient's async submit/poll/retrieve surface."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.uploaded_file_path: str | None = None
        self.created_endpoint_alias: str | None = None

    async def upload_jsonl(self, file_path, endpoint_alias, purpose="batch"):
        self.calls.append("upload_jsonl")
        self.uploaded_file_path = file_path
        return {"id": "file-123"}

    async def create_batch_job(self, input_file_id, endpoint_alias, endpoint="/v1/chat/completions", metadata=None):
        self.calls.append("create_batch_job")
        self.created_endpoint_alias = endpoint_alias
        assert input_file_id == "file-123"
        self.last_metadata = metadata
        return {"id": "batch-789", "status": "validating"}

    async def get_batch_status(self, batch_id, endpoint_alias):
        self.calls.append("get_batch_status")
        return {"status": "completed", "is_complete": True, "progress_percentage": 100}

    async def download_results(self, batch_id, endpoint_alias):
        self.calls.append("download_results")
        return {
            "success": True,
            "batch_id": batch_id,
            "responses": [
                {
                    "custom_id": "a",
                    "response": {
                        "body": {
                            "choices": [{"message": {"role": "assistant", "content": "batched answer"}}],
                            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                        }
                    },
                }
            ],
        }


def test_pg_llm_batch_backend_submits_and_retrieves() -> None:
    client = _FakeBatchApiClient()
    backend = PgLlmBatchBackend(client, endpoint_alias="prod_gateway")
    requests = [BatchRequest(messages=[{"role": "user", "content": "batch me"}], custom_id="a", model="gpt-x")]

    job = backend.submit(requests, metadata={"routing_reason": "latency-tolerant"})
    assert job.backend == "pg-llm-batch"
    assert job.job_id == "batch-789"
    assert client.calls == ["upload_jsonl", "create_batch_job"]
    assert client.created_endpoint_alias == "prod_gateway"
    assert client.last_metadata == {"routing_reason": "latency-tolerant"}

    status = backend.poll(job)
    assert status["is_complete"] is True

    results = backend.retrieve(job)
    assert len(results) == 1
    item = results[0]
    assert item.custom_id == "a"
    assert item.answer == "batched answer"
    assert item.prompt_tokens == 12
    assert item.completion_tokens == 8
    assert item.model == "gpt-x"
    assert "download_results" in client.calls


def test_pg_llm_batch_backend_incomplete_download_returns_empty() -> None:
    class _IncompleteClient(_FakeBatchApiClient):
        async def download_results(self, batch_id, endpoint_alias):
            return {"success": False, "reason": "Batch not complete"}

    backend = PgLlmBatchBackend(_IncompleteClient())
    job = backend.submit([BatchRequest(messages=[{"role": "user", "content": "x"}], custom_id="a")])
    assert backend.retrieve(job) == []


def test_build_jsonl_body_uses_openai_batch_line_shape() -> None:
    requests = [BatchRequest(messages=[{"role": "user", "content": "hi"}], custom_id="a", model="gpt-x")]
    body = build_jsonl_body(requests)
    assert '"custom_id": "a"' in body
    assert '"url": "/v1/chat/completions"' in body
    assert '"method": "POST"' in body


if __name__ == "__main__":  # pragma: no cover
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
    print("ok")
