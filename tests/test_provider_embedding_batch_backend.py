"""Focused synthetic contracts for provider-backed embedding batches."""

import threading
import time

import pytest

from contextual_orchestrator.batch_routing import (
    EmbeddingBatchRequest,
    ProviderEmbeddingBatchBackend,
)
from contextual_orchestrator import (
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    PriceBook,
    PriceEntry,
    TaskOrchestrator,
)
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.server import SecurityConfig, build_server
from contextual_orchestrator.token_counting import (
    TokenCountUnavailable,
    UnavailableEmbeddingTokenCounter,
)


class _SyntheticProviderClient(ModelClient):
    def __init__(self):
        super().__init__()
        self.embedding_calls = []

    def embed(self, agent, texts):
        self.embedding_calls.append(list(texts))
        return [[float(len(text))] for text in texts]

    def embed_with_usage(self, agent, texts):
        return self.embed(agent, texts), sum(len(text.encode("utf-8")) for text in texts)


class _SyntheticExactCounter:
    def count_text(self, text, model):
        """Return a deterministic synthetic authoritative count."""
        return len(text.split())


def test_unknown_tokenizer_uses_authoritative_provider_usage() -> None:
    """A byte-safe request completes only after the provider supplies exact usage."""
    agent = ModelAgent(
        "provider_embedding", "provider-embedding-model", "https://provider.synthetic.invalid/v1", tags=("embedding",)
    )
    orchestrator = TaskOrchestrator([agent], client=_SyntheticProviderClient())
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    price_book.set_price(
        PriceEntry("provider.synthetic.invalid", "provider-embedding-model", 1.0, 0.0)
    )
    coordinator = CostRoutingCoordinator(
        orchestrator,
        config,
        price_book=price_book,
        embedding_token_counter=UnavailableEmbeddingTokenCounter(),
    )

    document = coordinator.complete_embeddings_batch(["synthetic input"])

    assert document["status"] == "completed"
    assert document["total_tokens"] == len("synthetic input".encode("utf-8"))
    assert document["cost_micro_usd"] > 0


def test_unknown_tokenizer_rejects_missing_provider_usage() -> None:
    """Vectors without authoritative provider usage never become a successful job."""
    agent = ModelAgent(
        "provider_embedding", "provider-embedding-model", "https://provider.synthetic.invalid/v1", tags=("embedding",)
    )
    client = _SyntheticProviderClient()
    client.embed_with_usage = lambda agent, texts: (client.embed(agent, texts), None)
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([agent], client=client),
        embedding_token_counter=UnavailableEmbeddingTokenCounter(),
    )

    job = coordinator.submit_embeddings_batch(["synthetic input"])
    deadline = time.time() + 2
    while coordinator.embedding_batch_backend.poll(job)["status"] not in {"completed", "failed"} and time.time() < deadline:
        time.sleep(0.01)

    assert coordinator.embedding_batch_backend.poll(job)["status"] == "failed"


def test_unknown_tokenizer_fails_before_provider_when_byte_bound_exceeds_budget() -> None:
    """An unprovable preflight token budget never reaches provider I/O."""
    agent = ModelAgent(
        "provider_embedding", "provider-embedding-model", "https://provider.synthetic.invalid/v1", tags=("embedding",)
    )
    client = _SyntheticProviderClient()
    client.embed_with_usage = lambda *_args: (_ for _ in ()).throw(
        AssertionError("provider must not be called")
    )
    config = InMemoryConfigStore()
    config.set("routing", "embedding_max_tokens_per_request", 3)
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([agent], client=client),
        config,
        embedding_token_counter=UnavailableEmbeddingTokenCounter(),
    )

    with pytest.raises(TokenCountUnavailable):
        coordinator.submit_embeddings_batch(["four"])


@pytest.mark.parametrize("text", ["한글🙂e\u0301", "<|special|>", "\x00\U0010ffff"])
def test_unknown_tokenizer_byte_bound_never_becomes_recorded_usage(text) -> None:
    """Unicode byte proofs admit provider I/O but never masquerade as token usage."""
    agent = ModelAgent(
        "provider_embedding", "provider-embedding-model", "https://provider.synthetic.invalid/v1", tags=("embedding",)
    )
    client = _SyntheticProviderClient()
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([agent], client=client),
        embedding_token_counter=UnavailableEmbeddingTokenCounter(),
    )

    document = coordinator.complete_embeddings_batch([text])

    assert document["total_tokens"] == len(text.encode("utf-8"))


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


def test_server_shutdown_closes_embedding_workers() -> None:
    class ClosingBackend:
        name = "closing"
        closed = False

        def close(self):
            self.closed = True

    backend = ClosingBackend()
    orchestrator = TaskOrchestrator([ModelAgent("embedding_worker", "embedding-model")])
    coordinator = CostRoutingCoordinator(
        orchestrator,
        embedding_token_counter=_SyntheticExactCounter(),
        embedding_batch_backend=backend,
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="shutdown-token"),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    server.shutdown()
    thread.join(timeout=1)

    assert backend.closed is True


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
    coordinator.config.set("routing", "embedding_max_inputs_per_request", 2)

    document = coordinator.complete_embeddings_batch(
        ["one two", "three four", "five"],
        model=agent.model,
        agent_id=agent.id,
        wait_timeout=1,
    )

    assert document["status"] == "completed"
    assert client.embedding_calls == [["one two"], ["three four", "five"]]
