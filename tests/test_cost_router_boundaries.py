"""Boundary tests for cost-routing attribution, splitting, and reporting."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

import pytest

from contextual_orchestrator import (
    CostLedger,
    InMemoryConfigStore,
    ModelAgent,
    PriceBook,
    PriceEntry,
    TaskOrchestrator,
)
from contextual_orchestrator.batch_routing import (
    BatchJob,
    BatchResultItem,
    EmbeddingBatchResultItem,
)
from contextual_orchestrator.batch_job_registry import ClaimNotAcquired
from contextual_orchestrator.cost_router import (
    CostRoutingCoordinator as Coordinator,
)
from contextual_orchestrator.cost_router import (
    _positive_int,
    _provider_from_base_url,
    _weighted_average_embedding,
)
from contextual_orchestrator.token_counting import (
    TokenCountUnavailable,
    UnavailableEmbeddingTokenCounter,
)


class _ExactTestCounter:
    """Deterministic injected counter for synthetic embedding fixtures."""

    def count_text(self, text: str, model: str = "") -> int:
        return len(text.split())


def _coordinator(**kwargs: Any) -> Coordinator:
    agents = [
        ModelAgent(
            id="mock_worker",
            model="mock-a",
            base_url="mock://a",
            provider_name="mock",
            tags=("reasoning", "writing"),
        )
    ]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    if "token_counter" not in kwargs and "embedding_token_counter" not in kwargs:
        kwargs["embedding_token_counter"] = _ExactTestCounter()
    return Coordinator(orchestrator, config, price_book=price_book, **kwargs)


# --- sync attribution fallbacks -----------------------------------------------------


def test_sync_attribution_falls_back_when_trace_names_unknown_agent() -> None:
    coordinator = _coordinator()

    real_run = coordinator.orchestrator.run

    def run_with_ghost_trace(messages: Any, **kwargs: Any) -> Dict[str, Any]:
        result = real_run(messages, **kwargs)
        result["trace"] = [{"served_agent_id": "ghost_agent"}]
        return result

    coordinator.orchestrator.run = run_with_ghost_trace
    result = coordinator.complete([{"role": "user", "content": "hello"}])
    assert result["channel"] == "sync"
    row = coordinator.ledger.records()[0]
    # Unknown served agent degrades to provider "unknown" with the fallback model.
    assert row["provider_name"] == "unknown"
    assert row["model_name"] == "contextual-orchestrator"


def test_stream_usage_aggregates_trace_steps_without_text_estimates() -> None:
    coordinator = _coordinator()
    stream_result = {
        "workflow_run_id": "run_stream_usage",
        "mode": "conduct",
        "trace": [
            {"agent_id": "mock_worker", "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
            {"agent_id": "mock_worker", "usage": {"prompt_tokens": 11, "completion_tokens": 13}},
        ],
    }
    result = coordinator.record_stream_usage(
        result=stream_result,
        attribution={"team": "alpha"},
        model_name="requested-model",
    )

    assert result["usage"] == {"input_tokens": 16, "output_tokens": 20, "total_tokens": 36}
    assert result["cost"]["measurement_status"] == "measured"
    assert len(result["usage_record_ids"]) == 2
    rows = coordinator.ledger.records()
    assert [row["request_channel"] for row in rows] == ["stream", "stream"]
    assert all(row["measurement_status"] == "measured" for row in rows)
    coordinator.record_stream_usage(
        result=stream_result,
        attribution={"team": "alpha"},
        model_name="requested-model",
    )
    assert len(coordinator.ledger.records()) == 2


def test_complete_rejects_non_boolean_cache_bypass() -> None:
    coordinator = _coordinator()
    with pytest.raises(TypeError, match="cache_bypass"):
        coordinator.complete(
            [{"role": "user", "content": "hi"}], cache_bypass="true"  # type: ignore[arg-type]
        )


def test_complete_forwards_cache_partition_to_orchestrator() -> None:
    coordinator = _coordinator()
    seen: Dict[str, Any] = {}

    real_run = coordinator.orchestrator.run

    def spy_run(messages: Any, **kwargs: Any) -> Dict[str, Any]:
        seen.update(kwargs)
        return real_run(messages, **kwargs)

    coordinator.orchestrator.run = spy_run
    coordinator.complete(
        [{"role": "user", "content": "hi"}],
        cache_bypass=True,
        cache_partition="tenant-partition",
    )
    assert seen["bypass_cache"] is True
    assert seen["cache_partition"] == "tenant-partition"


# --- batch bookkeeping ---------------------------------------------------------------


def test_resolve_batch_provider_model_prefers_attribution_then_unknown() -> None:
    coordinator = _coordinator()
    provider, model = coordinator._resolve_batch_provider_model(
        BatchResultItem(custom_id="r1", answer="x", model="mock-a",
                        attribution={"upstream_api": "openrouter"})
    )
    assert (provider, model) == ("openrouter", "mock-a")
    provider, _ = coordinator._resolve_batch_provider_model(
        BatchResultItem(custom_id="r2", answer="y", attribution={})
    )
    assert provider == "unknown"


def test_retrieve_batch_requires_known_job_id() -> None:
    coordinator = _coordinator()
    with pytest.raises(KeyError, match="batch job"):
        coordinator.retrieve_batch("nope_missing_job")


def test_batch_poll_and_retrieve_require_the_bound_owner() -> None:
    """An opaque job identifier cannot cross the authenticated owner boundary."""
    coordinator = _coordinator()
    submitted = coordinator.complete(
        [{"role": "user", "content": "owned"}],
        hints={"channel": "batch"},
        owner_id="principal-a",
    )
    job_id = submitted["job_id"]
    job = coordinator._batch_jobs[job_id]

    assert job.owner_id == "principal-a"
    assert coordinator.poll_batch(job_id, owner_id="principal-a")["is_complete"] is True
    with pytest.raises(KeyError, match="batch job"):
        coordinator.poll_batch(job_id, owner_id="principal-b")
    with pytest.raises(KeyError, match="batch job"):
        coordinator.retrieve_batch(job_id, owner_id="principal-b")
    assert coordinator.retrieve_batch(job_id, owner_id="principal-a")["result_count"] == 1


# --- embedding input splitting --------------------------------------------------------


class _ExplodingCounter:
    def count_text(self, text: str, model: str) -> int:
        raise RuntimeError("counter backend offline")

    def count_messages(self, messages: Any, model: str = "") -> int:
        return 3


def test_embedding_token_count_propagates_counter_failure() -> None:
    coordinator = _coordinator(token_counter=_ExplodingCounter())
    with pytest.raises(RuntimeError, match="counter backend offline"):
        coordinator._count_embedding_tokens("alpha beta gamma", "mock-e")


class _ZeroCounter:
    def count_text(self, text: str, model: str) -> int:
        return 0 if text else 5

    def count_messages(self, messages: Any, model: str = "") -> int:
        return 1


def test_embedding_token_count_rejects_non_positive_authoritative_result() -> None:
    coordinator = _coordinator(token_counter=_ZeroCounter())
    with pytest.raises(RuntimeError, match="non-positive"):
        coordinator._count_embedding_tokens("nonempty", "mock-e")


def test_split_empty_input_yields_single_empty_part() -> None:
    coordinator = _coordinator()
    assert coordinator._split_embedding_input("", model="m", max_tokens=4, max_chars=10) == [("", 0)]
    assert coordinator._force_token_safe_chunks("", model="m", max_tokens=4, max_chars=10) == [("", 0)]


def test_split_uses_native_packer_when_available() -> None:
    class Counter:
        def pack_text(self, text: str, model: str, max_tokens: int):
            assert (text, model, max_tokens) == ("alpha beta", "text-embedding-3-small", 4)
            return [("alpha ", 2), ("beta", 1)]

    coordinator = _coordinator(token_counter=Counter())

    assert coordinator._split_embedding_input(
        "alpha beta", model="text-embedding-3-small", max_tokens=4, max_chars=100
    ) == [("alpha ", 2), ("beta", 1)]


class _WholeStringOnlyCounter:
    """Pathological counter: only the full original text exceeds the budget."""

    def __init__(self, full_text: str) -> None:
        self.full_text = full_text

    def count_text(self, text: str, model: str) -> int:
        return 99 if text == self.full_text else 1

    def count_messages(self, messages: Any, model: str = "") -> int:
        return 1


def test_split_bisects_when_unit_grouping_reproduces_the_original() -> None:
    text = "alpha beta"
    counter = _WholeStringOnlyCounter(text)
    coordinator = _coordinator(token_counter=counter)
    parts = coordinator._split_embedding_input(
        text, model="mock-e", max_tokens=10, max_chars=100
    )
    # The unit loop rebuilds the identical string, so bisection must terminate
    # with parts that individually satisfy both budgets.
    joined = "".join(part_text for part_text, _tokens in parts)
    assert joined == text
    assert all(tokens <= 10 for _part, tokens in parts)


def test_provider_from_base_url_handles_mock_host_and_malformed() -> None:
    assert _provider_from_base_url("mock://local") == "mock"
    assert _provider_from_base_url("https://api.openai.example/v1") == "api.openai.example"
    assert _provider_from_base_url("http://[::1-broken") == ""  # malformed IPv6


def test_positive_int_defaults_on_garbage_and_non_positive() -> None:
    assert _positive_int("7", 3) == 7
    assert _positive_int(None, 3) == 3
    assert _positive_int("abc", 3) == 3
    assert _positive_int(0, 3) == 3
    assert _positive_int(-2, 3) == 3
    assert _positive_int(True, 3) == 1  # bool coerces to 1, which is positive


# --- weighted average embedding reduction ----------------------------------------------


def test_weighted_average_empty_vectors_returns_empty() -> None:
    assert _weighted_average_embedding([]) == []
    assert _weighted_average_embedding([([], 5)]) == []


def test_weighted_average_clamps_degenerate_weights_to_one() -> None:
    reduced = _weighted_average_embedding([([2.0, 4.0], 0), ([4.0, 6.0], -1)])
    # Zero/negative weights clamp up to 1, so this is the plain part mean.
    assert reduced == [pytest.approx(3.0), pytest.approx(5.0)]


def test_weighted_average_respects_ragged_dimensions_and_weights() -> None:
    reduced = _weighted_average_embedding([([1.0, 3.0, 9.0], 3), ([2.0], 1)])
    assert reduced[0] == pytest.approx((1.0 * 3 + 2.0 * 1) / 4)
    assert reduced[1] == pytest.approx(9.0 / 4)  # short vector contributes zero
    assert reduced[2] == pytest.approx(27.0 / 4)


# --- embeddings batch document lifecycle -------------------------------------------------


class _DroppingEmbeddingBackend:
    """Local-shaped embedding backend that loses one requested vector."""

    name = "dropping"

    def __init__(self) -> None:
        self.jobs: Dict[str, BatchJob] = {}
        self.polled: List[str] = []

    def submit(self, requests: Any, metadata: Any = None) -> BatchJob:
        job = BatchJob(job_id=f"drop_{len(self.jobs)}", backend=self.name,
                       status="submitted", request_count=len(requests))
        self.jobs[job.job_id] = job
        self.requests = list(requests)
        return job

    def poll(self, job: BatchJob) -> Dict[str, Any]:
        self.polled.append(job.job_id)
        return {"job_id": job.job_id, "status": "completed", "is_complete": True}

    def retrieve(self, job: BatchJob) -> List[EmbeddingBatchResultItem]:
        # Drop the second request's result when one exists.
        dropped_id = self.requests[1].custom_id if len(self.requests) > 1 else None
        kept = [r for r in self.requests if r.custom_id != dropped_id]
        return [
            EmbeddingBatchResultItem(
                custom_id=request.custom_id,
                index=index,
                embedding=[float(index)],
                prompt_tokens=int(index + 1),
                model="contextual-orchestrator",
            )
            for index, request in enumerate(kept)
        ]


def test_embedding_submission_stops_before_backend_when_count_is_unavailable() -> None:
    """No provider work or cost record may follow an unavailable exact count."""
    backend = _DroppingEmbeddingBackend()
    coordinator = _coordinator(
        embedding_batch_backend=backend,
        embedding_token_counter=UnavailableEmbeddingTokenCounter(),
    )

    with pytest.raises(TokenCountUnavailable, match="no authoritative tokenizer"):
        coordinator.submit_embeddings_batch(["synthetic input"], model="unknown-embedding")

    assert backend.jobs == {}
    assert coordinator.ledger.records() == []


def test_embeddings_document_reports_placeholder_for_missing_parts() -> None:
    backend = _DroppingEmbeddingBackend()
    coordinator = _coordinator(embedding_batch_backend=backend)
    job = coordinator.submit_embeddings_batch(["one", "two"])
    document = coordinator.embeddings_batch_document(job.job_id)
    assert document["status"] == "completed"
    missing = document["embeddings"][1]
    assert missing == {"index": 1, "embedding": []}
    assert document["token_counts"][1] == 0


def test_embeddings_document_is_idempotent_after_completion() -> None:
    backend = _DroppingEmbeddingBackend()
    coordinator = _coordinator(embedding_batch_backend=backend)
    job = coordinator.submit_embeddings_batch(["only one"])
    first = coordinator.embeddings_batch_document(job.job_id)
    second = coordinator.embeddings_batch_document(job.job_id)
    assert first == second
    # The completed document cache means the backend is polled exactly once.
    assert backend.polled.count(job.job_id) == 1


def test_concurrent_embedding_polls_record_usage_once() -> None:
    backend = _DroppingEmbeddingBackend()
    coordinator = _coordinator(embedding_batch_backend=backend)
    job = coordinator.submit_embeddings_batch(["only one"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        documents = list(
            executor.map(
                lambda _index: coordinator.embeddings_batch_document(job.job_id),
                range(2),
            )
        )

    assert documents[0] == documents[1]
    assert len(coordinator.ledger.records()) == 1


def test_contended_embedding_document_claim_returns_cache_or_pending() -> None:
    backend = _DroppingEmbeddingBackend()
    coordinator = _coordinator(embedding_batch_backend=backend)
    job = coordinator.submit_embeddings_batch(["only one"])

    class _ContendedClaim:
        def __enter__(self):
            raise ClaimNotAcquired("owned by another poller")

        def __exit__(self, *_args):
            return False

    coordinator.job_registry.lock = lambda *_args, **_kwargs: _ContendedClaim()

    pending = coordinator.embeddings_batch_document(job.job_id)
    assert pending == {
        "batch_id": job.job_id,
        "status": "in_progress",
        "backend": job.backend,
        "model": "contextual-orchestrator",
        "embeddings": None,
    }

    cached = {**pending, "status": "completed", "embeddings": []}
    coordinator._embedding_documents[job.job_id] = cached
    assert coordinator.embeddings_batch_document(job.job_id) == cached


def test_embeddings_document_requires_known_batch() -> None:
    coordinator = _coordinator()
    with pytest.raises(KeyError, match="embeddings batch job"):
        coordinator.embeddings_batch_document("no_such_batch")


def test_embeddings_document_requires_the_bound_owner() -> None:
    coordinator = _coordinator(embedding_batch_backend=_DroppingEmbeddingBackend())
    job = coordinator.submit_embeddings_batch(["private"], owner_id="principal-a")

    with pytest.raises(KeyError, match="embeddings batch job"):
        coordinator.embeddings_batch_document(job.job_id, owner_id="principal-b")

    assert (
        coordinator.embeddings_batch_document(job.job_id, owner_id="principal-a")["status"]
        == "completed"
    )


def test_embeddings_document_incomplete_status_has_no_vectors() -> None:
    class _PendingBackend(_DroppingEmbeddingBackend):
        def poll(self, job: BatchJob) -> Dict[str, Any]:
            return {"job_id": job.job_id, "status": "in_progress", "is_complete": False}

    coordinator = _coordinator(embedding_batch_backend=_PendingBackend())
    job = coordinator.submit_embeddings_batch(["later"])
    document = coordinator.embeddings_batch_document(job.job_id)
    assert document["embeddings"] is None
    assert document["status"] == "in_progress"


def test_embeddings_document_preserves_failed_terminal_state_without_cost() -> None:
    class _FailedBackend(_DroppingEmbeddingBackend):
        def poll(self, job: BatchJob) -> Dict[str, Any]:
            return {
                "job_id": job.job_id,
                "status": "failed",
                "is_complete": True,
                "failure": {"error_type": "ProviderError", "retryable": False},
            }

        def retrieve(self, job: BatchJob) -> List[EmbeddingBatchResultItem]:
            raise AssertionError("failed jobs have no result payload")

    coordinator = _coordinator(embedding_batch_backend=_FailedBackend())
    job = coordinator.submit_embeddings_batch(["never billed"])

    document = coordinator.embeddings_batch_document(job.job_id)

    assert document["status"] == "failed"
    assert document["embeddings"] is None
    assert document["failure"]["error_type"] == "ProviderError"
    assert coordinator.ledger.records() == []


def test_embeddings_document_bills_the_selected_agent_not_caller_attribution() -> None:
    agent = ModelAgent(
        id="embedding_worker",
        model="embedding-v1",
        base_url="mock://embed",
        provider_name="trusted-provider",
        tags=("embedding",),
    )
    orchestrator = TaskOrchestrator([agent])
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("trusted-provider", "embedding-v1", 2.0, 0.0))
    coordinator = Coordinator(
        orchestrator,
        config,
        price_book=price_book,
        embedding_token_counter=_ExactTestCounter(),
        embedding_batch_backend=_DroppingEmbeddingBackend(),
    )

    coordinator.complete_embeddings_batch(
        ["bill selected route"],
        model="embedding-v1",
        agent_id=agent.id,
        attribution={"provider": "spoofed-provider"},
    )

    row = coordinator.ledger.records()[0]
    assert row["provider_name"] == "trusted-provider"
    assert row["model_name"] == "embedding-v1"


def test_cost_report_delegates_to_ledger_window() -> None:
    ledger = CostLedger(PriceBook(InMemoryConfigStore()))
    coordinator = _coordinator(ledger=ledger)
    assert coordinator.cost_report("model_name") == ledger.report("model_name")
    assert coordinator.cost_report("model_name", 5, 10) == ledger.report("model_name", 5, 10)


def test_sync_attribution_skips_trace_rows_without_agent_ids() -> None:
    coordinator = _coordinator()

    real_run = coordinator.orchestrator.run

    def run_with_blank_trace(messages: Any, **kwargs: Any) -> Dict[str, Any]:
        result = real_run(messages, **kwargs)
        result["trace"] = [{"served_agent_id": ""}, {"agent_id": None}]
        return result

    coordinator.orchestrator.run = run_with_blank_trace
    coordinator.complete([{"role": "user", "content": "hello"}])
    row = coordinator.ledger.records()[0]
    assert row["provider_name"] == "unknown"


def test_poll_batch_returns_backend_status_by_id() -> None:
    coordinator = _coordinator()
    job = coordinator.submit_batch([]) if hasattr(coordinator, "submit_batch") else None
    from contextual_orchestrator.batch_routing import BatchRequest

    job = coordinator.submit_batch([BatchRequest(messages=[{"role": "user", "content": "x"}])])
    status = coordinator.poll_batch(job.job_id)
    assert status["status"] == "completed"
    with pytest.raises(KeyError, match="batch job"):
        coordinator.poll_batch("missing_job_id")


class _LengthCounter:
    """Deterministic counter: tokens = len(text) // 2."""

    def count_text(self, text: str, model: str) -> int:
        return max(1, len(text) // 2)

    def count_messages(self, messages: Any, model: str = "") -> int:
        return 1


def test_split_bisects_single_unit_text_to_token_safe_halves() -> None:
    coordinator = _coordinator(token_counter=_LengthCounter())
    text = "aaaaaaaaaa"  # one regex unit; 10//2=5 tokens > budget of 4
    parts = coordinator._split_embedding_input(
        text, model="mock-e", max_tokens=4, max_chars=100
    )
    assert "".join(part for part, _tokens in parts) == text
    assert all(tokens <= 4 or part == "" for part, tokens in parts)


def test_split_respects_character_budget_before_token_budget() -> None:
    coordinator = _coordinator()
    text = "abcdefghij" * 3  # 30 chars
    parts = coordinator._split_embedding_input(
        text, model="mock-e", max_tokens=1000, max_chars=7
    )
    assert "".join(part for part, _tokens in parts) == text
    assert all(len(part) <= 7 for part, _tokens in parts)


class _SilentEmbeddingBackend(_DroppingEmbeddingBackend):
    """Backend that reports zero usage so the coordinator must recount."""

    def retrieve(self, job: BatchJob) -> List[EmbeddingBatchResultItem]:
        return [
            EmbeddingBatchResultItem(
                custom_id=request.custom_id,
                index=index,
                embedding=[1.0],
                prompt_tokens=0,
                model="contextual-orchestrator",
            )
            for index, request in enumerate(self.requests)
        ]


def test_document_recounts_tokens_when_backend_reports_zero_usage() -> None:
    coordinator = _coordinator(embedding_batch_backend=_SilentEmbeddingBackend())
    job = coordinator.submit_embeddings_batch(["alpha beta gamma"])
    document = coordinator.embeddings_batch_document(job.job_id)
    # The injected exact test seam counts whitespace-delimited fixture units.
    assert document["token_counts"] == [3]


def test_complete_embeddings_batch_round_trips_locally() -> None:
    backend = _DroppingEmbeddingBackend()
    coordinator = _coordinator(embedding_batch_backend=backend)
    document = coordinator.complete_embeddings_batch(
        ["single input"], attribution={"team": "ops"}
    )
    assert document["status"] == "completed"
    assert document["embeddings"][0]["index"] == 0
    assert document["cost_micro_usd"] >= 0



def test_batch_model_identity_error_does_not_capture_backend_value_errors() -> None:
    """Only model resolution receives the client-facing invalid-model category."""
    from contextual_orchestrator.batch_routing import BatchRequest
    from contextual_orchestrator.cost_router import InvalidBatchModelError

    class RejectingBackend:
        name = "rejecting-backend"

        def submit(self, requests, metadata=None):  # type: ignore[no-untyped-def]
            del requests, metadata
            raise ValueError("backend payload validation failed")

    coordinator = _coordinator(batch_backend=RejectingBackend())
    with pytest.raises(ValueError, match="backend payload validation failed") as backend_error:
        coordinator.submit_batch([
            BatchRequest(messages=[{"role": "user", "content": "valid"}], model="mock-a")
        ])
    assert type(backend_error.value) is ValueError

    with pytest.raises(InvalidBatchModelError, match="not configured"):
        coordinator.submit_batch([
            BatchRequest(
                messages=[{"role": "user", "content": "private"}],
                model="not-configured",
                zdr_only=True,
            )
        ])
