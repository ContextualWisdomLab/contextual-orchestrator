"""Behavioural coverage for batch routing, the cost ledger, and the router.

Covers the embeddings pg-llm-batch backend (driven by a fake async client that
mirrors ``BatchAPIClient``), batch/embedding edge cases, the non-blocking ledger
store's queue-full / flush-timeout / stored paths, SQL window queries, and the
cost-routing coordinator's split/token/embedding-document edge behaviours. Every
test asserts the real result, not just line execution.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.batch_routing import (  # noqa: E402
    BatchJob,
    EmbeddingBatchRequest,
    EmbeddingBatchResultItem,
    LocalEmbeddingBatchBackend,
    PgLlmBatchEmbeddingBackend,
    _extract_answer,
    _extract_embedding,
    build_embeddings_jsonl_body,
    cheapest_upstream,
    heuristic_embedding,
)
from contextual_orchestrator.cost_ledger import (  # noqa: E402
    AttributionDimensions,
    CostLedger,
    InMemoryLedgerStore,
    InMemoryUsageTelemetrySink,
    NonBlockingLedgerStore,
    PriceBook,
    PriceEntry,
    SqlLedgerStore,
    UsageRecord,
    _emit_usage_event,
)
from contextual_orchestrator.cost_router import (  # noqa: E402
    CostRoutingCoordinator,
    _positive_int,
    _provider_from_base_url,
    _weighted_average_embedding,
)
from contextual_orchestrator.kv_config import InMemoryConfigStore  # noqa: E402
from contextual_orchestrator.token_counting import HeuristicTokenCounter  # noqa: E402


# ---------------------------------------------------------------------------
# batch_routing: small edge helpers
# ---------------------------------------------------------------------------


def test_cheapest_upstream_returns_none_for_empty_candidates() -> None:
    assert cheapest_upstream([], price_book=None) is None


def test_extract_answer_and_embedding_handle_empty_bodies() -> None:
    assert _extract_answer({}) == ""
    assert _extract_answer({"choices": []}) == ""
    assert _extract_embedding({}) == []
    assert _extract_embedding({"data": [{"embedding": [1, 2]}]}) == [1.0, 2.0]


def test_heuristic_embedding_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError):
        heuristic_embedding("text", dimension=0)
    assert len(heuristic_embedding("text", dimension=4)) == 4


def test_local_embedding_backend_counts_tokens_without_counter() -> None:
    backend = LocalEmbeddingBatchBackend()
    job = backend.submit([EmbeddingBatchRequest(input_text="one two three", custom_id="e0")])
    item = backend.retrieve(job)[0]
    assert item.prompt_tokens == 3


def test_build_embeddings_jsonl_and_to_jsonl_line_use_embeddings_endpoint() -> None:
    body = build_embeddings_jsonl_body([EmbeddingBatchRequest(input_text="hi", custom_id="e1", model="emb-x")])
    assert '"url": "/v1/embeddings"' in body
    assert '"custom_id": "e1"' in body
    assert '"input": "hi"' in body


class _FakeEmbeddingApiClient:
    """Mimics pg_llm_batch.BatchAPIClient's async surface for the embeddings path."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.created_endpoint: str | None = None
        self.last_metadata: dict | None = None

    async def upload_jsonl(self, file_path, endpoint_alias, purpose="batch"):
        self.calls.append("upload_jsonl")
        return {"id": "file-emb"}

    async def create_batch_job(self, input_file_id, endpoint_alias, endpoint="/v1/embeddings", metadata=None):
        self.calls.append("create_batch_job")
        assert input_file_id == "file-emb"
        self.created_endpoint = endpoint
        self.last_metadata = metadata
        return {"id": "batch-emb", "status": "validating"}

    async def get_batch_status(self, batch_id, endpoint_alias):
        self.calls.append("get_batch_status")
        return {"status": "completed", "is_complete": True, "progress_percentage": 100}

    async def download_results(self, batch_id, endpoint_alias):
        self.calls.append("download_results")
        return {
            "success": True,
            "responses": [
                {"custom_id": "b", "response": {"body": {"data": [{"embedding": [0.3, 0.4]}], "usage": {"prompt_tokens": 5}}}},
                {"custom_id": "a", "response": {"body": {"data": [{"embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 3}}}},
            ],
        }


def test_pg_llm_batch_embedding_backend_submits_polls_and_orders_results() -> None:
    client = _FakeEmbeddingApiClient()
    backend = PgLlmBatchEmbeddingBackend(client, endpoint_alias="prod_gateway")
    requests = [
        EmbeddingBatchRequest(input_text="alpha", custom_id="a", model="emb-x"),
        EmbeddingBatchRequest(input_text="beta", custom_id="b", model="emb-x"),
    ]

    job = backend.submit(requests, metadata={"routing_reason": "bulk"})
    assert job.backend == "pg-llm-batch"
    assert job.job_id == "batch-emb"
    assert client.created_endpoint == "/v1/embeddings"
    assert client.last_metadata == {"routing_reason": "bulk"}
    assert backend.poll(job)["is_complete"] is True

    items = backend.retrieve(job)
    assert [item.custom_id for item in items] == ["a", "b"]
    assert [item.index for item in items] == [0, 1]
    assert items[0].embedding == [0.1, 0.2]
    assert items[0].prompt_tokens == 3
    assert items[1].model == "emb-x"


def test_pg_llm_batch_embedding_backend_incomplete_download_returns_empty() -> None:
    class _IncompleteClient(_FakeEmbeddingApiClient):
        async def download_results(self, batch_id, endpoint_alias):
            return {"success": False, "reason": "not complete"}

    backend = PgLlmBatchEmbeddingBackend(_IncompleteClient())
    job = backend.submit([EmbeddingBatchRequest(input_text="x", custom_id="a")])
    assert backend.retrieve(job) == []


def test_pg_llm_batch_embedding_backend_uses_payload_assembler_when_present() -> None:
    captured: dict = {}

    class _Assembler:
        def assemble(self, lines):
            captured["lines"] = lines
            return "memory://assembled"

    backend = PgLlmBatchEmbeddingBackend(_FakeEmbeddingApiClient(), payload_assembler=_Assembler())
    backend.submit([EmbeddingBatchRequest(input_text="hi", custom_id="a")])
    assert captured["lines"][0]["url"] == "/v1/embeddings"


# ---------------------------------------------------------------------------
# cost_ledger
# ---------------------------------------------------------------------------


def _record(record_id: str, created_at: int = 1) -> UsageRecord:
    return UsageRecord(
        usage_record_id=record_id,
        created_at=created_at,
        workflow_run_id=None,
        request_channel="sync",
        route_mode=None,
        provider_name="provider_name",
        model_name="model_name",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        cost_amount=0.0,
        currency_code="USD",
        attribution=AttributionDimensions.from_mapping({}),
    )


def test_in_memory_usage_telemetry_sink_evicts_oldest_past_cap() -> None:
    from contextual_orchestrator.cost_ledger import UsageTelemetryEvent

    sink = InMemoryUsageTelemetrySink(max_events=2)
    for index in range(4):
        sink.emit_usage(UsageTelemetryEvent.from_record(_record(f"u{index}"), export_state="queued"))
    kept = sink.events()
    assert len(kept) == 2
    assert [event.attributes["contextual_orchestrator.usage_record_id"] for event in kept] == ["u2", "u3"]


def test_emit_usage_event_swallows_sink_failures() -> None:
    from contextual_orchestrator.cost_ledger import UsageTelemetryEvent

    class _RaisingSink:
        def emit_usage(self, event) -> None:
            raise RuntimeError("sink down")

    assert _emit_usage_event(_RaisingSink(), UsageTelemetryEvent.from_record(_record("u0"), export_state="queued")) is None


def test_non_blocking_store_rejects_zero_queue_size() -> None:
    with pytest.raises(ValueError):
        NonBlockingLedgerStore(InMemoryLedgerStore(), queue_size=0)


def test_non_blocking_store_drops_on_full_queue_and_flush_reports_timeout_then_stores() -> None:
    class _BlockingBackend:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self.rows: list[UsageRecord] = []

        def append(self, record: UsageRecord) -> None:
            self.started.set()
            self.release.wait(timeout=5)
            self.rows.append(record)

        def query(self, start=None, end=None):
            return [row.as_dict() for row in self.rows]

    backend = _BlockingBackend()
    sink = InMemoryUsageTelemetrySink()
    store = NonBlockingLedgerStore(backend, queue_size=1, telemetry_sink=sink)

    store.append(_record("first"))
    assert backend.started.wait(timeout=5)
    store.append(_record("queued"))
    store.append(_record("dropped"))

    assert store.flush(timeout=0.05) is False
    health = store.telemetry_health()
    assert health["records_dropped"] == 1
    assert health["records_accepted"] == 2

    backend.release.set()
    assert store.flush(timeout=2.0) is True
    assert store.telemetry_health()["records_stored"] == 2
    assert len(store.query()) == 2
    dropped_events = [
        event
        for event in sink.events()
        if event.attributes["contextual_orchestrator.usage.export_state"] == "dropped"
    ]
    assert len(dropped_events) == 1


def test_in_memory_ledger_store_len_reflects_appended_rows() -> None:
    store = InMemoryLedgerStore()
    assert len(store) == 0
    store.append(_record("u0"))
    assert len(store) == 1


def _priced_ledger(**kwargs) -> CostLedger:
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", prompt_price_per_1k=2.0, completion_price_per_1k=4.0))
    return CostLedger(price_book, **kwargs)


def test_cost_ledger_wraps_store_when_non_blocking_requested() -> None:
    ledger = _priced_ledger(non_blocking_store=True)
    assert isinstance(ledger.store, NonBlockingLedgerStore)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=10, completion_tokens=5)
    assert ledger.flush(timeout=2.0)
    assert len(ledger.records()) == 1


def test_cost_ledger_accepts_prebuilt_attribution_dimensions() -> None:
    ledger = _priced_ledger()
    dims = AttributionDimensions.from_mapping({"team": "alpha", "company": "acme"})
    record = ledger.record_usage(
        provider="openai", model="gpt-x", prompt_tokens=10, completion_tokens=5, attribution=dims
    )
    row = record.as_dict()
    assert row["team_name"] == "alpha"
    assert row["company_name"] == "acme"


def test_cost_ledger_inline_store_failure_is_recorded_and_survives() -> None:
    class _FailingStore:
        def append(self, record) -> None:
            raise RuntimeError("P2028 with secret prompt")

        def query(self, start=None, end=None):
            return []

    sink = InMemoryUsageTelemetrySink()
    price_book = PriceBook(InMemoryConfigStore())
    price_book.set_price(PriceEntry("openai", "gpt-x", 2.0, 4.0))
    ledger = CostLedger(price_book, store=_FailingStore(), telemetry_sink=sink)

    record = ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=10, completion_tokens=5)
    assert record.usage_record_id.startswith("usage_")
    health = ledger.telemetry_health()
    assert health["store_failures"] == 1
    assert health["records_accepted"] == 1
    assert health["last_error_type"] == "RuntimeError"
    assert "P2028" not in repr(sink.events())


def test_cost_ledger_flush_is_noop_true_for_plain_store() -> None:
    assert _priced_ledger().flush() is True


def test_sql_ledger_store_query_honours_time_window() -> None:
    conn = sqlite3.connect(":memory:")
    store = SqlLedgerStore(conn, paramstyle="qmark")
    ledger = _priced_ledger(store=store)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=10, completion_tokens=0, created_at=100)
    ledger.record_usage(provider="openai", model="gpt-x", prompt_tokens=10, completion_tokens=0, created_at=300)
    assert len(store.query(150, 400)) == 1
    assert len(store.query(None, 200)) == 1
    assert len(store.query(200, None)) == 1
    assert len(store.query()) == 2


# ---------------------------------------------------------------------------
# cost_router: pure helpers + coordinator edge behaviours
# ---------------------------------------------------------------------------


def test_provider_from_base_url_maps_mock_and_remote_hosts() -> None:
    assert _provider_from_base_url("mock://local") == "mock"
    assert _provider_from_base_url("https://api.openai.com/v1") == "api.openai.com"


def test_positive_int_falls_back_on_invalid_or_non_positive() -> None:
    assert _positive_int("not-a-number", 5) == 5
    assert _positive_int(None, 5) == 5
    assert _positive_int(-3, 5) == 5
    assert _positive_int(12, 5) == 12


def test_weighted_average_embedding_empty_and_weighted() -> None:
    assert _weighted_average_embedding([]) == []
    assert _weighted_average_embedding([([], 1)]) == []
    assert _weighted_average_embedding([([2.0], 1), ([4.0], 3)]) == [3.5]


def _coordinator(**kwargs) -> CostRoutingCoordinator:
    orchestrator = TaskOrchestrator(
        [ModelAgent("mock_worker", "mock-a", "mock://a", provider_name="mock", tags=("reasoning",), priority=1)]
    )
    return CostRoutingCoordinator(orchestrator, InMemoryConfigStore(), **kwargs)


def test_served_provider_model_falls_back_when_agent_unresolvable() -> None:
    coordinator = _coordinator()
    provider, model = coordinator._served_provider_model(
        {"trace": [{"served_agent_id": "ghost_agent"}]}, "fallback-model"
    )
    assert (provider, model) == ("unknown", "fallback-model")


def test_batch_and_embedding_job_lookups_raise_for_unknown_ids() -> None:
    coordinator = _coordinator()
    with pytest.raises(KeyError):
        coordinator.poll_batch("missing_job")
    with pytest.raises(KeyError):
        coordinator.embeddings_batch_document("missing_job")


def test_force_token_safe_chunks_empty_and_single_unit_midpoint_split() -> None:
    coordinator = _coordinator()
    assert coordinator._split_embedding_input("", model="m", max_tokens=10, max_chars=10) == [("", 0)]
    assert coordinator._force_token_safe_chunks("", model="m", max_tokens=10, max_chars=10) == [("", 0)]
    chunks = coordinator._force_token_safe_chunks("abcdefgh", model="m", max_tokens=1, max_chars=100)
    assert "".join(text for text, _ in chunks) == "abcdefgh"
    assert len(chunks) > 1


def test_count_embedding_tokens_tolerates_counter_failure_and_zero() -> None:
    coordinator = _coordinator()
    assert coordinator._count_embedding_tokens(" ", "m") == 1

    class _RaisingCounter:
        def count_text(self, text, model):
            raise RuntimeError("boom")

        def count_messages(self, messages, model):
            return 0

    failing = _coordinator(token_counter=_RaisingCounter())
    assert failing._count_embedding_tokens("hi there", "m") == 2


def test_embeddings_batch_document_returns_pending_envelope_when_incomplete() -> None:
    class _PendingBackend:
        name = "pending"

        def submit(self, requests, metadata=None):
            self.requests = list(requests)
            return BatchJob(job_id="emb-pending", backend=self.name, status="validating", request_count=len(self.requests))

        def poll(self, job):
            return {"status": "validating", "is_complete": False}

        def retrieve(self, job):
            return []

    coordinator = _coordinator(embedding_batch_backend=_PendingBackend())
    job = coordinator.submit_embeddings_batch(["alpha"], attribution={"provider": "acme"})
    document = coordinator.embeddings_batch_document(job.job_id)
    assert document["status"] == "validating"
    assert document["embeddings"] is None
    assert coordinator.ledger.records() == []


def test_embeddings_batch_document_handles_missing_source_parts_and_zero_token_items() -> None:
    class _PartialBackend:
        name = "partial"

        def submit(self, requests, metadata=None):
            self.requests = list(requests)
            return BatchJob(job_id="emb-partial", backend=self.name, status="completed", request_count=len(self.requests))

        def poll(self, job):
            return {"status": "completed", "is_complete": True}

        def retrieve(self, job):
            first = self.requests[0]
            return [
                EmbeddingBatchResultItem(
                    custom_id=first.custom_id, index=0, embedding=[1.0], prompt_tokens=0, model=first.model
                )
            ]

    coordinator = _coordinator(embedding_batch_backend=_PartialBackend())
    document = coordinator.complete_embeddings_batch(
        ["alpha", "beta"], model="emb-x", attribution={"provider": "acme"}
    )
    assert [item["index"] for item in document["embeddings"]] == [0, 1]
    assert document["embeddings"][1]["embedding"] == []
    assert document["token_counts"][1] == 0
    assert document["token_counts"][0] > 0


if __name__ == "__main__":  # pragma: no cover
    import types

    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and isinstance(_fn, types.FunctionType):
            if _fn.__code__.co_argcount == 0:
                _fn()
                print(f"ok {_name}")
    print("ok")
