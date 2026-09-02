"""Focused synthetic contracts for provider-backed embedding batches."""

import threading
import time

import pytest

from contextual_orchestrator.batch_routing import (
    EmbeddingBatchRequest,
    ProviderEmbeddingBatchBackend,
)
from contextual_orchestrator.batch_job_registry import JobRegistryFactory
from contextual_orchestrator import (
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    PriceBook,
    PriceEntry,
    TaskOrchestrator,
)
from contextual_orchestrator.cost_router import _DEFAULT_EMBEDDING_CLAIM_LEASE_SECONDS
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.provider_errors import ProviderUpstreamError
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


def test_provider_batch_wait_survives_infinite_deadline() -> None:
    """A caller with no wall-clock deadline (``timeout=inf``) still completes.

    ``/v1/embeddings`` computes an ``inf`` remaining timeout when the client
    has no configured deadline (contextual-orchestrator's no-implicit-deadline
    default since #971). ``threading.Event.wait`` raises ``OverflowError`` for
    a non-finite timeout on CPython/Linux, so the backend must translate an
    infinite deadline into an unbounded (``None``) wait instead of passing it
    straight through.
    """
    release = threading.Event()

    def runner(requests):
        release.wait(timeout=1)
        return [[float(len(request.input_text))] for request in requests], 2

    backend = ProviderEmbeddingBatchBackend(runner)
    request = EmbeddingBatchRequest(input_text="synthetic input", model="synthetic-model")
    job = backend.submit([request])
    release.set()
    assert backend.wait(job, timeout=float("inf"))["status"] == "completed"
    assert backend.retrieve(job)[0].embedding == [15.0]
    backend.close()


def test_queued_document_exposes_backend_poll_and_registry_retention_contract() -> None:
    """Queued HTTP documents carry owned cadence/retention, not caller guesses."""
    release = threading.Event()

    def runner(requests):
        release.wait(timeout=1)
        return [[1.0] for _request in requests], len(requests)

    registry = JobRegistryFactory(retention_seconds=123)
    backend = ProviderEmbeddingBatchBackend(
        runner,
        job_registry=registry,
        claim_lease_seconds=None,
    )
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([], allow_empty_agents=True),
        embedding_batch_backend=backend,
        embedding_token_counter=_SyntheticExactCounter(),
        job_registry=registry,
    )
    job = coordinator.submit_embeddings_batch(["synthetic"], model="synthetic-model")

    document = coordinator.embeddings_batch_document(job.job_id)

    assert document["status"] in {"queued", "running"}
    assert document["poll_after_ms"] == backend.poll_after_ms
    assert document["job_retention_ms"] == 123_000
    release.set()
    assert backend.wait(job, timeout=1)["status"] == "completed"
    backend.close()


def test_provider_reservation_does_not_execute_before_public_registration() -> None:
    called = threading.Event()

    def runner(requests):
        called.set()
        return [[1.0] for _request in requests], len(requests)

    backend = ProviderEmbeddingBatchBackend(runner)
    job = backend.reserve(
        [EmbeddingBatchRequest(input_text="synthetic", model="synthetic-model")]
    )

    assert backend.poll(job)["status"] == "reserved"
    assert called.is_set() is False
    backend.start(job)
    assert backend.wait(job, timeout=1)["status"] == "completed"
    assert called.is_set() is True
    backend.close()


def test_provider_batch_failure_is_terminal_without_payload_leak() -> None:
    def runner(_requests):
        raise RuntimeError("synthetic provider failure")

    backend = ProviderEmbeddingBatchBackend(runner)
    job = backend.submit([EmbeddingBatchRequest(input_text="synthetic", model="synthetic-model")])
    assert backend.wait(job, timeout=1)["status"] == "failed"
    assert backend.retrieve(job) == []
    backend.close()


def test_provider_batch_failure_preserves_classified_provider_details() -> None:
    def runner(_requests):
        raise ProviderUpstreamError(
            agent_id="embedding_worker",
            model="embedding-model",
            error_code="rate_limit_exceeded",
            message="provider request failed",
            client_status=429,
            provider_status=503,
            retryable=True,
            transport="embedding",
        )

    backend = ProviderEmbeddingBatchBackend(runner)
    job = backend.submit(
        [EmbeddingBatchRequest(input_text="synthetic", model="embedding-model")]
    )

    failure = backend.wait(job, timeout=1)["failure"]
    assert failure["http_status"] == 429
    assert failure["provider_code"] == "rate_limit_exceeded"
    assert failure["retryable"] is True
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


def test_close_waits_for_start_to_submit_work() -> None:
    submit_entered = threading.Event()
    release_submit = threading.Event()
    shutdown_called = threading.Event()

    class Executor:
        def submit(self, *_args):
            submit_entered.set()
            assert release_submit.wait(timeout=1)

        def shutdown(self, **_kwargs):
            shutdown_called.set()

    backend = ProviderEmbeddingBatchBackend(lambda _requests: ([], 0))
    job = backend.reserve([])
    backend._executor = Executor()
    starter = threading.Thread(target=backend.start, args=(job,))
    starter.start()
    assert submit_entered.wait(timeout=1)

    closer = threading.Thread(target=backend.close)
    closer.start()
    assert not shutdown_called.wait(timeout=0.05)
    release_submit.set()
    starter.join(timeout=1)
    closer.join(timeout=1)
    assert shutdown_called.is_set()


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


def test_server_close_closes_embedding_workers_after_abnormal_exit() -> None:
    class ClosingBackend:
        name = "closing"
        closed = False

        def close(self):
            self.closed = True

    backend = ClosingBackend()
    orchestrator = TaskOrchestrator(
        [ModelAgent("embedding_worker", "embedding-model")]
    )
    coordinator = CostRoutingCoordinator(
        orchestrator,
        embedding_token_counter=_SyntheticExactCounter(),
        embedding_batch_backend=backend,
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="close-token"),
        coordinator=coordinator,
    )

    server.server_close()

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


def test_runtime_added_remote_embedding_member_uses_provider_backend() -> None:
    client = _SyntheticProviderClient()
    orchestrator = TaskOrchestrator([], client=client, allow_empty_agents=True)
    coordinator = CostRoutingCoordinator(
        orchestrator, embedding_token_counter=_SyntheticExactCounter()
    )
    orchestrator.add_agent(
        "default",
        ModelAgent(
            "runtime_embedding",
            "runtime-embedding-model",
            base_url="https://synthetic.invalid/v1",
            tags=("embedding",),
        ).to_config(),
    )

    document = coordinator.complete_embeddings_batch(
        ["provider input"], model="contextual-orchestrator", wait_timeout=1
    )

    assert document["status"] == "completed"
    assert client.embedding_calls == [["provider input"]]

    orchestrator.add_agent(
        "default",
        ModelAgent(
            "runtime_mock", "runtime-mock-model", base_url="mock://local", tags=("embedding",)
        ).to_config(),
    )
    local_document = coordinator.complete_embeddings_batch(
        ["local input"], agent_id="runtime_mock"
    )
    assert local_document["status"] == "completed"
    assert client.embedding_calls == [["provider input"]]


def test_local_startup_registers_provider_backend_for_recovered_jobs() -> None:
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([], allow_empty_agents=True),
        embedding_token_counter=_SyntheticExactCounter(),
    )

    assert isinstance(
        coordinator._embedding_backends["provider"], ProviderEmbeddingBatchBackend
    )


class _FakeValkeyClient:
    """The minimal hash/lock surface ``ValkeyJsonMapping``/``JobRegistryFactory`` use."""

    def hset(self, *_args, **_kwargs):
        """Accept a hash-field write; no data is actually persisted."""
        return 1

    def hget(self, *_args, **_kwargs):
        """Report every field as absent, matching a fresh empty hash."""
        return None

    def hgetall(self, *_args, **_kwargs):
        """Report an empty hash for any key."""
        return {}

    def hdel(self, *_args, **_kwargs):
        """Accept a hash-field delete; no data is actually persisted."""
        return 1

    def hkeys(self, *_args, **_kwargs):
        """Report no fields for any hash."""
        return []

    def hlen(self, *_args, **_kwargs):
        """Report an empty hash length."""
        return 0

    def expire(self, *_args, **_kwargs):
        """Accept a TTL refresh as a no-op."""
        return True

    def lock(self, *_args, **_kwargs):
        """Return a lock object that always acquires immediately."""

        class _Lock:
            def acquire(self, *_args, **_kwargs):
                """Always succeed synchronously."""
                return True

            def release(self):
                """No-op release."""

        return _Lock()


def test_durable_provider_embedding_backend_survives_unbounded_client_timeout() -> None:
    """A durable job registry must not require ``ModelClient.timeout`` to be set.

    Constructing the coordinator previously raised ``ValueError: durable
    provider backend claim lease must be positive`` whenever the client had
    no configured wall-clock timeout (contextual-orchestrator's
    no-implicit-deadline default since #971) and the job registry was
    durable (Valkey-backed) -- a startup crash caused by deriving the claim
    lease, an internal locking heartbeat, from that unrelated optional
    client attribute. The lease must fall back to a fixed positive default
    instead.
    """
    registry = JobRegistryFactory(client=_FakeValkeyClient())
    assert registry.durable is True
    agent = ModelAgent(
        "remote_embedding",
        "embed-v1",
        base_url="https://synthetic.invalid/v1",
        tags=("embedding",),
    )
    orchestrator = TaskOrchestrator([agent])
    assert orchestrator.client.timeout is None

    coordinator = CostRoutingCoordinator(orchestrator, job_registry=registry)

    backend = coordinator._embedding_backends["provider"]
    assert backend._claim_lease_seconds == _DEFAULT_EMBEDDING_CLAIM_LEASE_SECONDS
    backend.close()


def test_unbounded_execution_timeout_never_substitutes_registry_retention() -> None:
    """``execution_timeout_seconds=None`` stays genuinely unbounded.

    It previously fell back to the job registry's storage retention window
    (7 days by default), silently expiring an intentionally unbounded
    embedding job once that window elapsed -- contradicting #971's
    no-implicit-deadline policy. The per-job deadline must be ``+inf``, and
    a job that outlives the registry's default retention window must still
    complete rather than being force-failed as expired.
    """
    release = threading.Event()

    def runner(requests):
        release.wait(timeout=1)
        return [[float(len(request.input_text))] for request in requests], 2

    backend = ProviderEmbeddingBatchBackend(runner, execution_timeout_seconds=None)
    request = EmbeddingBatchRequest(input_text="synthetic input", model="synthetic-model")
    job = backend.submit([request])
    assert backend._execution_deadline(job.job_id) == float("inf")
    release.set()
    assert backend.wait(job, timeout=1)["status"] == "completed"
    backend.close()


def test_server_closes_provider_backend_added_after_startup() -> None:
    orchestrator = TaskOrchestrator([], allow_empty_agents=True)
    coordinator = CostRoutingCoordinator(
        orchestrator, embedding_token_counter=_SyntheticExactCounter()
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="runtime_backend_close_token"),
        coordinator=coordinator,
    )
    closed = threading.Event()
    coordinator._embedding_backends["provider"].close = closed.set

    server.server_close()

    assert closed.is_set()


def test_recovered_privacy_scoped_embedding_batch_revalidates_current_agent_tags() -> None:
    """A pinned ``zdr_only`` route must still satisfy ZDR at execution time.

    ``ProviderEmbeddingBatchBackend`` replays a durably-queued job's pinned
    ``agent_id`` after a process restart recovers it -- an arbitrarily long
    gap in which an operator could remove the agent's ``privacy:zdr`` tag or
    repoint it to a non-ZDR route. Executing a request whose stored
    ``zdr_only=True`` against an agent that no longer carries that tag must
    fail closed instead of silently sending the batch through an unverified
    route.
    """
    agent = ModelAgent(
        "reconfigured_embedding",
        "reconfigured-embedding-model",
        base_url="https://synthetic.invalid/v1",
        tags=("embedding",),  # privacy:zdr was revoked since this batch was submitted
    )
    client = _SyntheticProviderClient()
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([agent], client=client),
        embedding_token_counter=_SyntheticExactCounter(),
    )
    stale_request = EmbeddingBatchRequest(
        input_text="synthetic input",
        model=agent.model,
        zdr_only=True,
        agent_id=agent.id,
    )

    with pytest.raises(RuntimeError, match="zdr_only"):
        coordinator._run_provider_embeddings([stale_request])
    assert client.embedding_calls == []


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
