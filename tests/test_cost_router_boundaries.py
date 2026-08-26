"""Boundary tests for cost-routing attribution, splitting, and reporting."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

import pytest

from contextual_orchestrator import (
    CostLedger,
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    PriceBook,
    TaskOrchestrator,
)
from contextual_orchestrator.batch_routing import (
    BatchJob,
    BatchResultItem,
    EmbeddingBatchResultItem,
)
from contextual_orchestrator.cost_router import (
    CostRoutingCoordinator as Coordinator,
)
from contextual_orchestrator.cost_router import (
    _positive_int,
    _provider_from_base_url,
)


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


# --- embedding input splitting --------------------------------------------------------


class _ExplodingCounter:
    def count_text(self, text: str, model: str) -> int:
        raise RuntimeError("counter backend offline")

    def count_messages(self, messages: Any, model: str = "") -> int:
        return 3


def test_embedding_token_count_tolerates_counter_failure_and_clamps() -> None:
    coordinator = _coordinator(token_counter=_ExplodingCounter())
    # Adapter failure falls back to whitespace units.
    assert coordinator._count_embedding_tokens("alpha beta gamma", "mock-e") == 3
    assert coordinator._count_embedding_tokens("", "mock-e") == 0


class _ZeroCounter:
    def count_text(self, text: str, model: str) -> int:
        return 0 if text else 5

    def count_messages(self, messages: Any, model: str = "") -> int:
        return 1


def test_embedding_token_count_clamps_positive_text_to_one() -> None:
    coordinator = _coordinator(token_counter=_ZeroCounter())
    assert coordinator._count_embedding_tokens("nonempty", "mock-e") == 1


def test_split_empty_input_yields_single_empty_part() -> None:
    coordinator = _coordinator()
    assert coordinator._split_embedding_input("", model="m", max_tokens=4, max_chars=10) == [("", 0)]
    assert coordinator._force_token_safe_chunks("", model="m", max_tokens=4, max_chars=10) == [("", 0)]


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


def test_concurrent_terminal_materialization_records_cost_once() -> None:
    backend = _DroppingEmbeddingBackend()
    coordinator = _coordinator(embedding_batch_backend=backend)
    coordinator._cl100k_packer = type(
        "RustFixture", (), {
            "weighted_average_embeddings": staticmethod(lambda parts: parts[0][0]),
            "sum_token_counts": staticmethod(sum),
        }
    )()
    job = coordinator.submit_embeddings_batch(["only one"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        documents = list(pool.map(lambda _index: coordinator.embeddings_batch_document(job.job_id), range(2)))
    assert documents[0] == documents[1]
    assert len(coordinator.ledger.records()) == 1


def test_cancelling_completed_batch_preserves_terminal_document() -> None:
    backend = _DroppingEmbeddingBackend()
    backend.cancel = lambda job, reason: {"status": "completed", "is_complete": True}
    coordinator = _coordinator(embedding_batch_backend=backend)
    coordinator._cl100k_packer = type(
        "RustFixture", (), {
            "weighted_average_embeddings": staticmethod(lambda parts: parts[0][0]),
            "sum_token_counts": staticmethod(sum),
        }
    )()
    job = coordinator.submit_embeddings_batch(["only one"])
    completed = coordinator.embeddings_batch_document(job.job_id)
    assert coordinator.cancel_embeddings_batch(job.job_id, reason="too late") == completed


def test_embeddings_document_requires_known_batch() -> None:
    coordinator = _coordinator()
    with pytest.raises(KeyError, match="embeddings batch job"):
        coordinator.embeddings_batch_document("no_such_batch")


def test_embeddings_document_incomplete_status_has_no_vectors() -> None:
    class _PendingBackend(_DroppingEmbeddingBackend):
        def poll(self, job: BatchJob) -> Dict[str, Any]:
            return {"job_id": job.job_id, "status": "in_progress", "is_complete": False}

    coordinator = _coordinator(embedding_batch_backend=_PendingBackend())
    job = coordinator.submit_embeddings_batch(["later"])
    document = coordinator.embeddings_batch_document(job.job_id)
    assert document["embeddings"] is None
    assert document["status"] == "in_progress"


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
    # HeuristicTokenCounter counts word units with the BPE expansion factor.
    assert document["token_counts"] == [4]
    assert document["token_count_provenance"] == ["measured_or_estimated_per_input"]


def test_complete_embeddings_batch_round_trips_locally() -> None:
    backend = _DroppingEmbeddingBackend()
    coordinator = _coordinator(embedding_batch_backend=backend)
    document = coordinator.complete_embeddings_batch(
        ["single input"], attribution={"team": "ops"}
    )
    assert document["status"] == "completed"
    assert document["embeddings"][0]["index"] == 0
    assert document["cost_micro_usd"] >= 0
