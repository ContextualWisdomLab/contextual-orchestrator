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
    def embed(self, agent, texts):
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
