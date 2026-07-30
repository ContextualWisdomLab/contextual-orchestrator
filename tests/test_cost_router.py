"""Cost-routing coordinator: records usage on every sync + batch completion."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    CostLedger,
    CostRoutingCoordinator,
    InMemoryUsageTelemetrySink,
    InMemoryConfigStore,
    ModelAgent,
    NonBlockingLedgerStore,
    PriceBook,
    PriceEntry,
    TaskOrchestrator,
)
from contextual_orchestrator.batch_routing import PgLlmBatchBackend  # noqa: E402
from contextual_orchestrator.cost_router import (  # noqa: E402
    _positive_int,
    _provider_from_base_url,
    _weighted_average_embedding,
)


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


# --- module helpers + defensive edge branches --------------------------------


def test_provider_from_base_url_variants() -> None:
    """mock scheme, real host extraction, empty input, and a malformed URL that
    must fall through the guarded parse to an empty string (never raise)."""
    assert _provider_from_base_url("mock://a") == "mock"
    assert _provider_from_base_url("https://api.openai.com/v1") == "api.openai.com"
    assert _provider_from_base_url("") == ""
    assert _provider_from_base_url("http://[::1") == ""  # malformed -> guarded fallback


def test_positive_int_parses_and_falls_back_to_default() -> None:
    assert _positive_int("5", 1) == 5
    assert _positive_int("x", 7) == 7  # ValueError -> default
    assert _positive_int(None, 7) == 7  # TypeError -> default
    assert _positive_int("-3", 9) == 9  # non-positive -> default
    assert _positive_int("0", 9) == 9


def test_weighted_average_embedding_edges_and_mean() -> None:
    assert _weighted_average_embedding([]) == []
    assert _weighted_average_embedding([([], 3), ([], 2)]) == []  # no non-empty vectors
    # (1*[1,0] + 3*[3,4]) / 4 == [2.5, 3.0]
    assert _weighted_average_embedding([([1.0, 0.0], 1), ([3.0, 4.0], 3)]) == [2.5, 3.0]


def test_batch_and_embedding_lookups_raise_keyerror_for_unknown_ids() -> None:
    coordinator = _coordinator()
    with pytest.raises(KeyError):
        coordinator.poll_batch("nope")
    with pytest.raises(KeyError):
        coordinator.retrieve_batch("nope")
    with pytest.raises(KeyError):
        coordinator.embeddings_batch_document("nope")


def test_split_embedding_input_handles_empty_and_oversize_no_whitespace() -> None:
    coordinator = _coordinator()
    assert coordinator._split_embedding_input("", model="m", max_tokens=8, max_chars=8) == [("", 0)]
    assert coordinator._force_token_safe_chunks("", model="m", max_tokens=8, max_chars=8) == [("", 0)]
    # Over max_chars -> fixed-width char split.
    chunks = coordinator._force_token_safe_chunks("x" * 40, model="m", max_tokens=1000, max_chars=8)
    assert len(chunks) > 1
    assert all(len(text) <= 8 for text, _ in chunks)

    # Within max_chars but token-dense and a single unit (no unit split helps) ->
    # the midpoint-recursion fallback keeps splitting until each chunk fits.
    class _PerCharCounter:
        def count_text(self, text, model):
            return len(text)  # one token per character

    coordinator.token_counter = _PerCharCounter()
    dense = coordinator._force_token_safe_chunks("abcdefgh", model="m", max_tokens=1, max_chars=8)
    assert len(dense) == 8
    assert all(len(text) <= 1 for text, _ in dense)


def test_count_embedding_tokens_tolerates_counter_failure_and_zero() -> None:
    coordinator = _coordinator()

    class _Raising:
        def count_text(self, text, model):
            raise RuntimeError("counter down")

    class _Zero:
        def count_text(self, text, model):
            return 0

    coordinator.token_counter = _Raising()
    assert coordinator._count_embedding_tokens("a b c", "m") == 3  # word-count fallback
    coordinator.token_counter = _Zero()
    assert coordinator._count_embedding_tokens("abc", "m") == 1  # non-empty but 0 -> 1
    assert coordinator._count_embedding_tokens("", "m") == 0  # empty -> 0


# --- remaining branch coverage: provider resolution + embeddings document ---


def test_served_provider_model_falls_back_when_agent_lookup_raises() -> None:
    """A trace naming an agent the orchestrator cannot resolve falls back to
    ``('unknown', fallback_model)`` instead of raising."""
    coordinator = _coordinator()
    provider, model = coordinator._served_provider_model(
        {"trace": [{"served_agent_id": "__no_such_agent__"}]}, "fallback-model"
    )
    assert (provider, model) == ("unknown", "fallback-model")


class _FakeJob:
    """Minimal BatchJob-shaped handle a fake embedding backend can return."""


def _embedding_coordinator(backend):
    """A coordinator wired to an explicit embeddings backend."""
    agents = [
        ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a", provider_name="mock",
                   tags=("reasoning", "coding", "writing"), priority=1),
    ]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("mock", "mock-a", prompt_price_per_1k=1.0, completion_price_per_1k=2.0))
    return CostRoutingCoordinator(
        orchestrator, config, price_book=price_book, embedding_batch_backend=backend
    )


def test_embeddings_batch_document_returns_pending_while_incomplete() -> None:
    """A backend whose poll is not complete yields the pending document
    (``embeddings is None``) and does not record any cost."""
    from contextual_orchestrator.batch_routing import BatchJob

    class _Pending:
        def submit(self, requests, metadata=None):
            return BatchJob(job_id="emb-pending", backend="fake", status="processing",
                            request_count=len(requests))

        def poll(self, job):
            return {"is_complete": False, "status": "processing"}

        def retrieve(self, job):  # pragma: no cover - not reached while pending
            return []

    coordinator = _embedding_coordinator(_Pending())
    job = coordinator.submit_embeddings_batch(["hello world"], attribution={"team": "a"})
    doc = coordinator.embeddings_batch_document(job.job_id)
    assert doc["embeddings"] is None
    assert doc["status"] == "processing"
    assert doc["backend"] == "fake"
    assert coordinator.ledger.records() == []


def test_embeddings_batch_document_token_fallback_and_empty_source() -> None:
    """An item with non-positive prompt_tokens whose request has a zero
    token_count triggers the count_text fallback, and a source input that
    receives no returned item yields an empty embedding entry."""
    from contextual_orchestrator.batch_routing import BatchJob, EmbeddingBatchResultItem

    class _CompleteSourceZeroOnly:
        def __init__(self):
            self._requests = []

        def submit(self, requests, metadata=None):
            self._requests = list(requests)
            return BatchJob(job_id="emb-done", backend="fake", status="completed",
                            request_count=len(requests))

        def poll(self, job):
            return {"is_complete": True, "status": "completed"}

        def retrieve(self, job):
            # Return an item only for source 0 (the "" input -> token_count 0),
            # with prompt_tokens 0 so the count_text fallback runs. Source 1
            # gets no item, so its parts list stays empty.
            return [
                EmbeddingBatchResultItem(
                    custom_id=r.custom_id, index=i, embedding=[1.0, 2.0],
                    prompt_tokens=0, model=r.model,
                )
                for i, r in enumerate(self._requests)
                if r.source_index == 0
            ]

    coordinator = _embedding_coordinator(_CompleteSourceZeroOnly())
    job = coordinator.submit_embeddings_batch(["", "world"], attribution={"team": "a"})
    doc = coordinator.embeddings_batch_document(job.job_id)
    # Two source inputs -> two embedding entries; source 1 received no item.
    by_index = {entry["index"]: entry for entry in doc["embeddings"]}
    assert by_index[1]["embedding"] == []  # empty-source branch
    assert by_index[0]["embedding"]  # source 0 produced a reduced vector
    assert doc["token_counts"][1] == 0
