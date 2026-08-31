"""Focused synthetic contracts for provider-backed embedding batches."""

import threading
import time

from contextual_orchestrator.batch_routing import (
    EmbeddingBatchRequest,
    ProviderEmbeddingBatchBackend,
)
from contextual_orchestrator import CostRoutingCoordinator, ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient


class _SyntheticProviderClient(ModelClient):
    def __init__(self):
        super().__init__()
        self.embedding_calls = []

    def embed(self, agent, texts):
        self.embedding_calls.append(list(texts))
        return [[float(len(text))] for text in texts]


class _SyntheticExactCounter:
    def count_text(self, text, model):
        """Return a deterministic synthetic authoritative count."""
        return len(text.split())


def test_provider_batch_returns_before_terminal_result() -> None:
    release = threading.Event()

    def runner(requests):
        release.wait(timeout=1)
        return [[float(len(request.input_text))] for request in requests], 2

    backend = ProviderEmbeddingBatchBackend(runner)
    request = EmbeddingBatchRequest(input_text="synthetic input", model="synthetic-model")
    started = time.monotonic()
    job = backend.submit([request])
    assert time.monotonic() - started < 0.1
    release.set()
    assert backend.wait(job, timeout=1)["status"] == "completed"
    assert backend.retrieve(job)[0].embedding == [15.0]
    assert backend.usage(job) == {"prompt_tokens": 2}
    backend.close()


def test_provider_batch_failure_is_terminal_without_payload_leak() -> None:
    def runner(_requests):
        raise RuntimeError("synthetic provider failure")

    backend = ProviderEmbeddingBatchBackend(runner)
    job = backend.submit([EmbeddingBatchRequest(input_text="synthetic", model="synthetic-model")])
    assert backend.wait(job, timeout=1)["status"] == "failed"
    assert backend.retrieve(job) == []
    backend.close()


def test_provider_batch_cancellation_preserves_the_reason() -> None:
    release = threading.Event()

    def runner(_requests):
        release.wait(timeout=1)
        return [[1.0]], 1

    backend = ProviderEmbeddingBatchBackend(runner)
    job = backend.submit(
        [EmbeddingBatchRequest(input_text="synthetic", model="synthetic-model")]
    )
    backend.cancel(job, reason="synchronous request deadline elapsed")

    assert backend.poll(job)["cancellation"] == {
        "reason": "synchronous request deadline elapsed"
    }
    release.set()
    backend.close()


def test_remote_embedding_member_selects_provider_backend() -> None:
    agent = ModelAgent(
        "synthetic_embedding",
        "synthetic-embedding-model",
        base_url="https://synthetic.invalid/v1",
        tags=("embedding",),
    )
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([agent], client=_SyntheticProviderClient()),
        embedding_token_counter=_SyntheticExactCounter(),
    )
    job = coordinator.submit_embeddings_batch(
        ["synthetic one", "synthetic two"], model=agent.model, agent_id=agent.id
    )
    for _attempt in range(100):
        document = coordinator.embeddings_batch_document(job.job_id)
        if document["status"] == "completed":
            break
        time.sleep(0.01)
    assert document["status"] == "completed"
    assert [item["embedding"] for item in document["embeddings"]] == [[13.0], [13.0]]


def test_provider_embedding_requests_are_sharded_by_the_existing_token_limit() -> None:
    agent = ModelAgent(
        "synthetic_embedding",
        "synthetic-embedding-model",
        base_url="https://synthetic.invalid/v1",
        tags=("embedding",),
    )
    client = _SyntheticProviderClient()
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([agent], client=client),
        embedding_token_counter=_SyntheticExactCounter(),
    )
    coordinator.config.set("routing", "embedding_max_tokens_per_request", 3)

    document = coordinator.complete_embeddings_batch(
        ["one two", "three four", "five"],
        model=agent.model,
        agent_id=agent.id,
        wait_timeout=1,
    )

    assert document["status"] == "completed"
    assert client.embedding_calls == [["one two"], ["three four", "five"]]
