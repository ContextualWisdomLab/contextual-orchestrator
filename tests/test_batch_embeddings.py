"""End-to-end contract test for the batch embeddings endpoint.

This is a *real* contract test, not a mock: it drives the actual HTTP server
(``build_server``) over a live loopback socket, submits the shared contract
request through the in-process ``LocalEmbeddingBatchBackend``, and asserts the
response matches the ``{batch_id, status, embeddings, cost_micro_usd,
token_counts}`` shape naruon's ``batch_embedding_service`` parses.

The request and the response keys are loaded from
``tests/fixtures/batch_embeddings_contract.json`` — the same fixture naruon
keeps a byte-identical copy of and asserts its client against — so the two
services cannot drift out of contract.
"""

from __future__ import annotations

from pathlib import Path
import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    CostRoutingCoordinator,
    InMemoryConfigStore,
    ModelAgent,
    PriceBook,
    PriceEntry,
    TaskOrchestrator,
)
from contextual_orchestrator.batch_routing import (  # noqa: E402
    BatchJob,
    EmbeddingBatchRequest,
    EmbeddingBatchResultItem,
    ProviderEmbeddingBatchBackend,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    ProviderResponseError,
    RequestDeadlineExceeded,
    _provider_limit_contract,
)
from contextual_orchestrator.token_counting import HeuristicTokenCounter  # noqa: E402
from contextual_orchestrator.batch_job_registry import JobRegistryFactory  # noqa: E402
from contextual_orchestrator.embedding_capabilities import EmbeddingModelCapability  # noqa: E402


CONTRACT = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "batch_embeddings_contract.json").read_text(
        encoding="utf-8"
    )
)


def _serve(*, embedding_batch_backend=None, security=None):
    agents = [
        ModelAgent(
            id="mock_worker",
            model="mock-a",
            base_url="mock://a",
            provider_name="mock",
            tags=("reasoning", "coding", "writing"),
            priority=1,
        ),
        ModelAgent(
            id="embedding_worker",
            model="text-embedding-test",
            base_url="mock://embed",
            provider_name="acme-provider",
            tags=("embedding", "offline_test"),
            priority=2,
        ),
    ]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    # Price the embeddings provider so cost is a real, non-zero number.
    price_book.set_price(
        PriceEntry("acme-provider", "text-embedding-test", prompt_price_per_1k=0.13, completion_price_per_1k=0.0)
    )
    coordinator = CostRoutingCoordinator(
        orchestrator,
        config,
        price_book=price_book,
        embedding_batch_backend=embedding_batch_backend,
    )
    token = "cost_token"
    server = build_server(
        orchestrator,
        port=0,
        security=security or SecurityConfig(auth_token=token),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1], token, coordinator


def _request(method, url, token=None, body=None, extra_headers=None):
    headers = {"content-type": "application/json"}
    headers.update(extra_headers or {})
    if token:
        headers["authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:  # pragma: no cover - surfaced in asserts
        return exc.code, json.loads(exc.read())


def test_embedding_endpoints_apply_the_caller_deadline() -> None:
    server, port, token, coordinator = _serve()
    observed: list[float | None] = []
    original = coordinator.complete_embeddings_batch

    def complete(*args, **kwargs):
        observed.append(
            coordinator.orchestrator.client.request_settings_snapshot()[
                "request_deadline_monotonic"
            ]
        )
        return original(*args, **kwargs)

    coordinator.complete_embeddings_batch = complete  # type: ignore[method-assign]
    try:
        for path, payload in (
            ("/v1/embeddings", {"model": "text-embedding-test", "input": "evidence"}),
            ("/v1/batch/embeddings", {"model": "text-embedding-test", "inputs": ["evidence"]}),
        ):
            status, _document = _request(
                "POST",
                f"http://127.0.0.1:{port}{path}",
                token,
                payload,
                {"x-request-timeout-ms": "180000"},
            )
            assert status == 200
    finally:
        server.shutdown()

    assert len(observed) == 2
    assert all(deadline is not None for deadline in observed)


def test_batch_capabilities_publish_enforced_request_and_partition_limits() -> None:
    server, port, token, _coordinator = _serve()
    try:
        status, document = _request(
            "GET", f"http://127.0.0.1:{port}/v1/batch/embeddings/capabilities", token
        )
        assert status == 200
        assert document == {
            "max_request_body_bytes": 64 * 1024,
            "max_tokens_per_part": 280_000,
            "max_chars_per_part": 240_000,
            "poll_after_ms": 1_000,
            "job_retention_ms": 7 * 24 * 60 * 60 * 1_000,
        }
    finally:
        server.shutdown()


def test_openai_large_embedding_capability_is_exact_and_authority_tagged() -> None:
    """Publish OpenAI's limits only for the exact provider/model pair."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "openai_embedding",
                "text-embedding-3-large",
                provider_name="openai",
                tags=("embedding",),
            )
        ]
    )
    coordinator = CostRoutingCoordinator(orchestrator)
    document = coordinator.embedding_batch_capabilities(
        max_request_body_bytes=64 * 1024, poll_after_ms=1_000
    )
    assert document["model"] == "text-embedding-3-large"
    assert document["max_inputs"] == 2048
    assert document["max_tokens_per_part"] == 8192
    assert document["max_total_tokens"] == 300_000
    assert document["tokenizer"] == "cl100k_base"
    assert document["capability_authority_url"].startswith("https://developers.openai.com/")


def test_openai_large_embedding_input_uses_exact_tokenizer_and_8192_limit() -> None:
    """Split an oversized OpenAI input using exact cl100k token counts."""
    agent = ModelAgent(
        "openai_embedding",
        "text-embedding-3-large",
        provider_name="openai",
        tags=("embedding",),
    )
    coordinator = CostRoutingCoordinator(TaskOrchestrator([agent]))
    requests, part_counts, limits = coordinator._build_embedding_requests(
        ["token " * 9_000],
        model=agent.model,
        attribution={},
        routing_agent_id=agent.id,
    )
    assert part_counts[0] > 1
    assert limits["max_tokens_per_part"] == 8192
    assert all(0 < request.token_count <= 8192 for request in requests)


def test_provider_batch_returns_immediately_then_polls_terminal_result() -> None:
    release = threading.Event()
    calls = []

    def runner(requests):
        calls.append(list(requests))
        release.wait(timeout=1)
        return [[float(len(request.input_text))] for request in requests], 2

    backend = ProviderEmbeddingBatchBackend(runner)
    request = EmbeddingBatchRequest(input_text="synthetic input", model="synthetic-model")
    started = time.monotonic()
    job = backend.submit([request])

    assert time.monotonic() - started < 0.1
    assert backend.poll(job)["status"] in {"queued", "running"}
    release.set()
    for _attempt in range(100):
        if backend.poll(job)["status"] == "completed":
            break
        time.sleep(0.01)
    assert backend.poll(job) == {
        "job_id": job.job_id,
        "status": "completed",
        "is_complete": True,
    }
    assert backend.retrieve(job)[0].embedding == [15.0]
    assert len(calls) == 1
    assert len(calls[0]) == 1
    assert backend.usage(job) == {"prompt_tokens": 2}


def test_provider_batch_exposes_failed_terminal_state() -> None:
    def runner(_requests):
        raise RuntimeError("synthetic provider failure")

    backend = ProviderEmbeddingBatchBackend(runner)
    job = backend.submit(
        [EmbeddingBatchRequest(input_text="synthetic input", model="synthetic-model")]
    )
    for _attempt in range(100):
        if backend.poll(job)["status"] == "failed":
            break
        time.sleep(0.01)
    assert backend.poll(job)["is_complete"] is True
    assert backend.retrieve(job) == []


def test_identical_submission_retries_after_backend_terminal_failure() -> None:
    class FailedBackend:
        name = "failed-provider"

        def __init__(self):
            self.submissions = 0

        def submit(self, requests, metadata=None):
            del metadata
            self.submissions += 1
            return BatchJob(
                f"failed_{self.submissions}", self.name, "queued", len(requests)
            )

        def poll(self, job):
            return {"job_id": job.job_id, "status": "failed", "is_complete": True}

    backend = FailedBackend()
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([ModelAgent("worker_agent", "mock", tags=("reasoning",))]),
        embedding_batch_backend=backend,
    )
    first = coordinator.submit_embeddings_batch(["same"], model="embedding-model")
    second = coordinator.submit_embeddings_batch(["same"], model="embedding-model")
    assert first.job_id != second.job_id
    assert backend.submissions == 2


def test_provider_batch_cancel_is_terminal_and_discards_late_result() -> None:
    release = threading.Event()

    def runner(requests):
        release.wait(timeout=1)
        return [[1.0] for _request in requests], len(requests)

    backend = ProviderEmbeddingBatchBackend(runner)
    job = backend.submit(
        [EmbeddingBatchRequest(input_text="synthetic input", model="synthetic-model")]
    )
    cancelled = backend.cancel(job, reason="superseded_by_true_bulk_runner")
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancellation"] == {"reason": "superseded_by_true_bulk_runner"}
    release.set()
    time.sleep(0.02)
    assert backend.poll(job)["status"] == "cancelled"
    assert backend.retrieve(job) == []


def test_provider_batch_cancelled_while_queued_never_starts() -> None:
    release = threading.Event()
    calls: list[str] = []

    def runner(requests):
        calls.append(requests[0].input_text)
        release.wait(timeout=1)
        return [[1.0]], 1

    backend = ProviderEmbeddingBatchBackend(runner, max_concurrency=1)
    first = backend.submit([EmbeddingBatchRequest(input_text="first", model="model")])
    second = backend.submit([EmbeddingBatchRequest(input_text="second", model="model")])
    backend.cancel(second, reason="queued cancellation")
    release.set()
    assert backend.wait(first, timeout=1.0)["is_complete"]
    assert backend.wait(second, timeout=1.0)["is_complete"]
    assert backend.poll(second)["status"] == "cancelled"
    assert calls == ["first"]


def test_provider_backend_context_manager_closes_executor() -> None:
    backend = ProviderEmbeddingBatchBackend(lambda requests: ([], 0))
    with backend:
        pass
    assert backend._executor._shutdown


def test_sync_provider_embeddings_wait_for_remote_completion() -> None:
    release = threading.Event()
    agent = ModelAgent(
        "embedding_worker", "remote-embedding", base_url="https://provider.example/v1",
        provider_name="provider", tags=("embedding",),
    )
    orchestrator = TaskOrchestrator([agent])

    def embed_with_usage(_agent, texts):
        release.wait(timeout=1)
        return [[1.0] for _text in texts], len(texts)

    orchestrator.client.embed_with_usage = embed_with_usage  # type: ignore[method-assign]
    threading.Timer(0.05, release.set).start()
    document = CostRoutingCoordinator(orchestrator).complete_embeddings_batch(
        ["alpha"], model=agent.model, routing_agent_id=agent.id
    )
    assert document["status"] == "completed"
    assert document["embeddings"][0]["embedding"] == [1.0]


def test_provider_batch_total_keeps_per_input_token_counts_explicitly_unknown() -> None:
    backend = ProviderEmbeddingBatchBackend(
        lambda requests: ([[1.0] for _request in requests], 17)
    )
    agent = ModelAgent("embedding_worker", "mock-embedding", tags=("embedding",))
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([agent]), embedding_batch_backend=backend
    )
    document = coordinator.complete_embeddings_batch(["alpha", "beta"], wait_for_terminal=True)
    assert document["total_tokens"] == 17
    assert document["token_counts"] == [0, 0]
    assert document["token_count_provenance"] == [
        "unknown_provider_batch_total_only",
        "unknown_provider_batch_total_only",
    ]


def test_sync_provider_embeddings_wait_is_bounded_by_caller_deadline() -> None:
    agent = ModelAgent(
        "embedding_worker", "remote-embedding", base_url="https://provider.example/v1",
        provider_name="provider", tags=("embedding",),
    )
    orchestrator = TaskOrchestrator([agent])
    release = threading.Event()

    def embed_with_usage(_agent, texts):
        release.wait(timeout=1)
        orchestrator.client.remaining_request_timeout()
        return [[1.0] for _text in texts], len(texts)

    orchestrator.client.embed_with_usage = embed_with_usage  # type: ignore[method-assign]
    coordinator = CostRoutingCoordinator(orchestrator)
    with orchestrator.client.request_settings(
        request_deadline_monotonic=time.monotonic() + 0.02
    ):
        try:
            with pytest.raises(RequestDeadlineExceeded):
                coordinator.complete_embeddings_batch(
                    ["alpha"], model=agent.model, routing_agent_id=agent.id
                )
        finally:
            release.set()


def test_provider_batch_sends_more_than_32_inputs_in_one_provider_call() -> None:
    calls = []

    def runner(requests):
        calls.append(list(requests))
        return [[float(index)] for index, _request in enumerate(requests)], 40

    backend = ProviderEmbeddingBatchBackend(runner)
    requests = [
        EmbeddingBatchRequest(
            input_text=f"synthetic input {index}", model="synthetic-model"
        )
        for index in range(40)
    ]
    job = backend.submit(requests)
    for _attempt in range(100):
        if backend.poll(job)["status"] == "completed":
            break
        time.sleep(0.01)

    assert backend.poll(job)["status"] == "completed"
    assert len(calls) == 1
    assert len(calls[0]) == 40
    assert len(backend.retrieve(job)) == 40
    assert backend.usage(job) == {"prompt_tokens": 40}


def test_provider_declared_maximum_drives_server_side_batch_split() -> None:
    class LimitAdvertisingClient:
        local_concurrency = 1

        def __init__(self) -> None:
            self.calls = []

        def embed_with_usage(self, _agent, texts):
            self.calls.append(list(texts))
            if len(texts) > 40:
                raise ProviderResponseError(
                    "synthetic explicit limit",
                    status_code=413,
                    provider_code="too_many_inputs",
                    max_inputs=40,
                )
            return [[float(index)] for index, _text in enumerate(texts)], len(texts)

    client = LimitAdvertisingClient()
    agent = ModelAgent(
        id="embedding_worker",
        model="text-embedding-test",
        base_url="https://provider.example/v1",
        tags=("embedding",),
    )
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([agent], client=client), InMemoryConfigStore()
    )
    created = coordinator.complete_embeddings_batch(
        [f"synthetic input {index}" for index in range(80)],
        model="text-embedding-test",
        routing_agent_id="embedding_worker",
    )
    for _attempt in range(100):
        document = coordinator.embeddings_batch_document(created["batch_id"])
        if document["status"] == "completed":
            break
        time.sleep(0.01)

    assert document["status"] == "completed"
    assert [len(call) for call in client.calls] == [80, 40, 40]
    assert len(document["embeddings"]) == 80
    assert document["total_tokens"] == 80
    assert document["batch_token_count"] == 80
    assert coordinator.embedding_batch_capabilities(
        max_request_body_bytes=65_536, poll_after_ms=1_000
    )["max_inputs"] == 40


def test_provider_shard_resume_reuses_completed_shards_in_original_order(monkeypatch) -> None:
    """A retry resumes only an unfinished provider shard and preserves index order."""
    capability = EmbeddingModelCapability(
        "openai", "text-embedding-3-large", 2, 10, 2, "cl100k_base", "https://example.test"
    )
    monkeypatch.setattr(
        "contextual_orchestrator.cost_router.embedding_model_capability",
        lambda provider, model: capability if provider == "openai" else None,
    )

    class SharedRegistry(JobRegistryFactory):
        def __init__(self):
            super().__init__()
            self.values = {}

        def mapping(self, name, *, decode=None):
            return self.values.setdefault(name, {})

    class Client:
        local_concurrency = 1

        def __init__(self, fail_second):
            self.fail_second = fail_second
            self.calls = []

        def embed_with_usage(self, _agent, texts):
            self.calls.append(list(texts))
            if self.fail_second and texts == ["third"]:
                raise ProviderResponseError("synthetic terminal")
            return [[float(ord(text[0]))] for text in texts], len(texts)

    registry = SharedRegistry()
    agent = ModelAgent(
        "openai_embedding", "text-embedding-3-large", base_url="https://provider.example/v1",
        provider_name="openai", tags=("embedding",),
    )
    first_client = Client(True)
    first = CostRoutingCoordinator(
        TaskOrchestrator([agent], client=first_client),
        job_registry=registry,
    )
    created = first.complete_embeddings_batch(
        ["alpha", "beta", "third"], model=agent.model, routing_agent_id=agent.id
    )
    for _attempt in range(100):
        failed = first.embeddings_batch_document(created["batch_id"])
        if failed["status"] == "failed":
            break
        time.sleep(0.01)
    assert [len(call) for call in first_client.calls] == [2, 1]

    second_client = Client(False)
    second = CostRoutingCoordinator(
        TaskOrchestrator([agent], client=second_client),
        job_registry=registry,
    )
    retried = second.complete_embeddings_batch(
        ["alpha", "beta", "third"], model=agent.model,
        routing_agent_id=agent.id, attribution={"workflow_run": "retry"},
    )
    for _attempt in range(100):
        document = second.embeddings_batch_document(retried["batch_id"])
        if document["status"] == "completed":
            break
        time.sleep(0.01)
    assert second_client.calls == [["third"]]
    assert [item["embedding"] for item in document["embeddings"]] == [[97.0], [98.0], [116.0]]


def test_concurrent_identical_shards_have_one_provider_receipt(monkeypatch) -> None:
    """Concurrent retries share one atomic claim and incur one provider call."""
    capability = EmbeddingModelCapability(
        "openai", "text-embedding-3-large", 2048, 8192, 300_000,
        "cl100k_base", "https://example.test",
    )
    monkeypatch.setattr(
        "contextual_orchestrator.cost_router.embedding_model_capability",
        lambda provider, model: capability if provider == "openai" else None,
    )

    class Client:
        local_concurrency = 2

        def __init__(self) -> None:
            self.calls = 0
            self.guard = threading.Lock()

        def embed_with_usage(self, _agent, texts):
            with self.guard:
                self.calls += 1
            time.sleep(0.05)
            return [[float(index)] for index, _text in enumerate(texts)], len(texts)

    client = Client()
    registry = JobRegistryFactory()
    agent = ModelAgent(
        "openai_embedding", "text-embedding-3-large",
        base_url="https://provider.example/v1", provider_name="openai",
        tags=("embedding",),
    )
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([agent], client=client), job_registry=registry,
    )
    jobs = [
        coordinator.complete_embeddings_batch(
            ["alpha", "beta"], model=agent.model, routing_agent_id=agent.id,
        )["batch_id"]
        for _ in range(2)
    ]
    for _attempt in range(200):
        documents = [coordinator.embeddings_batch_document(job) for job in jobs]
        if all(document["status"] == "completed" for document in documents):
            break
        time.sleep(0.01)

    assert all(document["status"] == "completed" for document in documents)
    assert client.calls == 1
    assert documents[0]["embeddings"] == documents[1]["embeddings"]


def test_sync_embedding_waits_for_remote_provider_terminal_state(monkeypatch) -> None:
    """The synchronous compatibility endpoint waits within its request budget."""
    capability = EmbeddingModelCapability(
        "openai", "text-embedding-3-large", 2048, 8192, 300_000,
        "cl100k_base", "https://example.test",
    )
    monkeypatch.setattr(
        "contextual_orchestrator.cost_router.embedding_model_capability",
        lambda provider, model: capability if provider == "openai" else None,
    )

    class Client:
        local_concurrency = 1
        timeout = 1.0

        def remaining_request_timeout(self):
            return 1.0

        def embed_with_usage(self, _agent, texts):
            time.sleep(0.03)
            return [[1.0] for _text in texts], len(texts)

    agent = ModelAgent(
        "openai_embedding", "text-embedding-3-large",
        base_url="https://provider.example/v1", provider_name="openai",
        tags=("embedding",),
    )
    coordinator = CostRoutingCoordinator(TaskOrchestrator([agent], client=Client()))
    document = coordinator.complete_embeddings_batch(
        ["alpha"], model=agent.model, routing_agent_id=agent.id,
        wait_for_terminal=True,
    )
    assert document["status"] == "completed"
    assert document["embeddings"][0]["embedding"] == [1.0]


def test_cancelled_queued_job_cannot_be_restarted() -> None:
    """A queued cancellation wins atomically over the worker start transition."""
    release = threading.Event()
    calls: list[str] = []

    def runner(requests):
        calls.append(requests[0].input_text)
        release.wait(timeout=1)
        return [[1.0]], 1

    backend = ProviderEmbeddingBatchBackend(runner, max_concurrency=1)
    first = backend.submit([EmbeddingBatchRequest("first")])
    second = backend.submit([EmbeddingBatchRequest("second")])
    assert backend.cancel(second, reason="superseded")["status"] == "cancelled"
    release.set()
    for _attempt in range(100):
        if backend.poll(first)["is_complete"]:
            break
        time.sleep(0.01)
    time.sleep(0.03)
    assert backend.poll(second)["status"] == "cancelled"
    assert calls == ["first"]


def test_failed_deduplicated_job_is_replaced_by_retry(monkeypatch) -> None:
    """Dedup consults durable backend state before returning a prior job."""
    capability = EmbeddingModelCapability(
        "openai", "text-embedding-3-large", 2048, 8192, 300_000,
        "cl100k_base", "https://example.test",
    )
    monkeypatch.setattr(
        "contextual_orchestrator.cost_router.embedding_model_capability",
        lambda provider, model: capability if provider == "openai" else None,
    )

    class Client:
        local_concurrency = 1

        def __init__(self):
            self.fail = True

        def embed_with_usage(self, _agent, texts):
            if self.fail:
                raise ProviderResponseError("synthetic terminal")
            return [[1.0] for _text in texts], len(texts)

    client = Client()
    agent = ModelAgent(
        "openai_embedding", "text-embedding-3-large",
        base_url="https://provider.example/v1", provider_name="openai",
        tags=("embedding",),
    )
    coordinator = CostRoutingCoordinator(TaskOrchestrator([agent], client=client))
    first = coordinator.submit_embeddings_batch(
        ["alpha"], model=agent.model, routing_agent_id=agent.id,
    )
    for _attempt in range(100):
        if coordinator.embeddings_batch_document(first.job_id)["status"] == "failed":
            break
        time.sleep(0.01)
    client.fail = False
    second = coordinator.submit_embeddings_batch(
        ["alpha"], model=agent.model, routing_agent_id=agent.id,
    )
    assert second.job_id != first.job_id


def test_provider_limit_parser_keeps_only_machine_readable_limits() -> None:
    error = urllib.error.HTTPError(
        "https://provider.example/v1/embeddings",
        413,
        "too large",
        {},
        io.BytesIO(
            json.dumps(
                {
                    "error": {
                        "code": "too_many_inputs",
                        "max_inputs": 64,
                        "max_tokens": 8192,
                        "message": "provider text that must not be retained",
                    }
                }
            ).encode()
        ),
    )
    assert _provider_limit_contract(error) == ("too_many_inputs", 64, 8192)

class _RecordingEmbeddingBackend:
    """Embedding backend that records the exact mapped requests it receives."""

    name = "recording"

    def __init__(self) -> None:
        self.requests: list[EmbeddingBatchRequest] = []
        self._results: list[EmbeddingBatchResultItem] = []
        self.submit_count = 0

    def submit(self, requests, metadata=None):
        self.submit_count += 1
        self.requests = list(requests)
        self._results = [
            EmbeddingBatchResultItem(
                custom_id=request.custom_id,
                index=position,
                embedding=[
                    float(request.source_index),
                    float(request.part_index),
                    float(request.token_count),
                ],
                prompt_tokens=request.token_count,
                model=request.model,
            )
            for position, request in enumerate(self.requests)
        ]
        return BatchJob(
            job_id="recording-embeddings",
            backend=self.name,
            status="completed",
            request_count=len(self.requests),
        )

    def poll(self, job):
        return {"job_id": job.job_id, "status": "completed", "is_complete": True}

    def retrieve(self, job):
        return list(self._results)


class _PendingEmbeddingBackend(_RecordingEmbeddingBackend):
    def submit(self, requests, metadata=None):
        super().submit(requests, metadata)
        return BatchJob("pending-embeddings", self.name, "in_progress", len(requests))

    def poll(self, job):
        return {"job_id": job.job_id, "status": "in_progress", "is_complete": False}


def test_pending_http_batch_declares_rate_budget_polling_cadence() -> None:
    security = SecurityConfig(
        auth_token="cost_token", rate_limit_requests=4, rate_limit_window_seconds=2
    )
    server, port, token, _coordinator = _serve(
        embedding_batch_backend=_PendingEmbeddingBackend(), security=security
    )
    base = f"http://127.0.0.1:{port}"
    try:
        status, created = _request(
            "POST",
            f"{base}/v1/batch/embeddings",
            token,
            {"model": "text-embedding-test", "inputs": ["synthetic input"]},
        )
        assert status == 202
        assert created["poll_after_ms"] == 500
        assert created["job_retention_ms"] == 7 * 24 * 60 * 60 * 1_000

        time.sleep(created["poll_after_ms"] / 1000)
        status, polled = _request(
            "GET", f"{base}/v1/batch/embeddings/{created['batch_id']}", token
        )
        assert status == 200
        assert polled["poll_after_ms"] == 500
        assert polled["job_retention_ms"] == 7 * 24 * 60 * 60 * 1_000
    finally:
        server.shutdown()


def test_identical_embedding_submission_reuses_durable_job() -> None:
    agent = ModelAgent(
        id="mock_worker",
        model="mock-a",
        base_url="mock://a",
        tags=("embedding",),
    )
    backend = _PendingEmbeddingBackend()
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([agent]),
        InMemoryConfigStore(),
        embedding_batch_backend=backend,
    )

    first = coordinator.submit_embeddings_batch(
        ["synthetic input"], input_metadata=[{"session_id": "synthetic-session"}]
    )
    second = coordinator.submit_embeddings_batch(
        ["synthetic input"], input_metadata=[{"session_id": "synthetic-session"}]
    )

    assert second.job_id == first.job_id
    assert backend.submit_count == 1


def test_batch_embeddings_endpoint_matches_naruon_contract() -> None:
    server, port, token, coordinator = _serve()
    base = f"http://127.0.0.1:{port}"
    request = CONTRACT["request"]
    submit_path = CONTRACT["endpoint"]["submit_path"]
    response_keys = CONTRACT["response"]["required_keys"]
    item_keys = CONTRACT["response"]["embedding_item_keys"]
    try:
        # Submit through the real endpoint with a provider dimension so the
        # ledger prices the priced provider/model above (non-zero cost).
        payload = {
            "model": request["model"],
            "endpoint": request["endpoint"],
            "inputs": request["inputs"],
            "metadata": {**request["metadata"], "provider": "acme-provider"},
        }
        status, document = _request("POST", f"{base}{submit_path}", token, payload)
        assert status == 200, document

        # Exact response shape naruon parses.
        for key in response_keys:
            assert key in document, f"missing contract key: {key}"
        assert document["status"] == CONTRACT["response"]["status_completed"]

        embeddings = document["embeddings"]
        assert isinstance(embeddings, list)
        assert len(embeddings) == len(request["inputs"])
        for position, item in enumerate(embeddings):
            for key in item_keys:
                assert key in item
            assert item["index"] == position
            assert isinstance(item["embedding"], list) and item["embedding"]

        token_counts = document["token_counts"]
        assert len(token_counts) == len(request["inputs"])
        assert all(count > 0 for count in token_counts)
        assert document["total_tokens"] == sum(token_counts)

        # Cost was actually computed and recorded in micro-USD.
        assert isinstance(document["cost_micro_usd"], int)
        assert document["cost_micro_usd"] > 0

        batch_id = document["batch_id"]

        # Polling the batch id returns the same completed document (idempotent),
        # and does NOT double-record usage in the ledger.
        records_after_submit = len(coordinator.ledger.records())
        poll_path = CONTRACT["endpoint"]["poll_path_template"].format(batch_id=batch_id)
        status, polled = _request("GET", f"{base}{poll_path}", token)
        assert status == 200
        assert polled["batch_id"] == batch_id
        assert polled["status"] == "completed"
        assert polled["embeddings"] == embeddings
        assert len(coordinator.ledger.records()) == records_after_submit

        # Cost is attributed across every dimension naruon sends in metadata.
        for dimension in CONTRACT["attribution_dimensions_in_metadata"]:
            status, report = _request(
                "GET", f"{base}/api/v1/cost_reports/rollup?dimension={dimension}", token
            )
            assert status == 200, report
            values = {item["dimension_value"] for item in report["items"]}
            expected = request["metadata"][dimension]
            assert expected in values, f"dimension {dimension} not attributed to {expected}"
    finally:
        server.shutdown()


def test_batch_embeddings_accepts_openai_style_input_field() -> None:
    """The endpoint also accepts the OpenAI-style ``input`` (string or list)."""
    server, port, token, _coordinator = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, document = _request(
            "POST",
            f"{base}/v1/batch/embeddings",
            token,
            {"model": "text-embedding-test", "input": "single string input"},
        )
        assert status == 200, document
        assert len(document["embeddings"]) == 1
        assert document["status"] == "completed"
    finally:
        server.shutdown()


def test_batch_embeddings_http_preserves_index_aligned_input_context() -> None:
    """Bulk HTTP outputs retain each input's session metadata and attribution."""
    server, port, token, coordinator = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, document = _request(
            "POST",
            f"{base}/v1/batch/embeddings",
            token,
            {
                "model": "text-embedding-test",
                "inputs": ["first", "second"],
                "input_attributions": [{"team": "alpha"}, {"team": "beta"}],
                "input_metadata": [
                    {"session_id": "session-a"},
                    {"session_id": "session-b"},
                ],
            },
        )
        assert status == 200, document
        assert [item["metadata"]["session_id"] for item in document["embeddings"]] == [
            "session-a",
            "session-b",
        ]
        assert [item["attribution"]["session_id"] for item in document["embeddings"]] == [
            "session-a",
            "session-b",
        ]
        assert [record["team_name"] for record in coordinator.ledger.records()] == [
            "alpha",
            "beta",
        ]
    finally:
        server.shutdown()


def test_batch_embeddings_preserves_top_level_session_in_durable_attribution() -> None:
    """One post session survives submission, polling, and usage attribution."""
    server, port, token, _coordinator = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, document = _request(
            "POST",
            f"{base}/v1/batch/embeddings",
            token,
            {
                "model": "text-embedding-test",
                "inputs": ["first", "second"],
                "session_id": "post-session-a",
            },
        )
        assert status == 200, document
        assert {
            item["attribution"]["session_id"] for item in document["embeddings"]
        } == {"post-session-a"}
    finally:
        server.shutdown()


def test_pending_batch_preserves_resolved_model_identity() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("embedding_worker", "resolved-embedding")])
    coordinator = CostRoutingCoordinator(
        orchestrator,
        InMemoryConfigStore(),
        embedding_batch_backend=_PendingEmbeddingBackend(),
    )

    created = coordinator.complete_embeddings_batch(["alpha"], model="resolved-embedding")
    polled = coordinator.embeddings_batch_document(created["batch_id"])

    assert created["model"] == "resolved-embedding"
    assert polled["model"] == "resolved-embedding"


def test_empty_batch_preserves_resolved_model_identity() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("embedding_worker", "resolved-embedding")])
    coordinator = CostRoutingCoordinator(orchestrator, InMemoryConfigStore())

    document = coordinator.complete_embeddings_batch([], model="resolved-embedding")

    assert document["model"] == "resolved-embedding"


def test_blank_embedding_input_fails_before_backend_selection() -> None:
    """Direct coordinator callers cannot send an empty part to any provider."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "embedding_worker",
                "resolved-embedding",
                base_url="https://provider.example/v1",
                tags=("embedding",),
            )
        ]
    )
    coordinator = CostRoutingCoordinator(orchestrator, InMemoryConfigStore())

    try:
        coordinator.complete_embeddings_batch([""], model="resolved-embedding")
    except ValueError as exc:
        assert str(exc) == "embedding inputs must be non-empty strings"
    else:
        raise AssertionError("empty embedding input must fail closed")


def test_batch_embeddings_split_oversized_inputs_before_backend() -> None:
    """Large embedding inputs are mapped into provider-safe parts, then reduced."""
    agents = [
        ModelAgent(
            id="mock_worker",
            model="mock-a",
            base_url="mock://a",
            provider_name="mock",
            tags=("reasoning",),
            priority=1,
        )
    ]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    config.set("routing", "embedding_max_tokens_per_request", 4)
    config.set("routing", "embedding_max_chars_per_part", 200)
    price_book = PriceBook(config)
    price_book.set_price(PriceEntry("acme-provider", "text-embedding-test", 1.0, 0.0))
    backend = _RecordingEmbeddingBackend()
    coordinator = CostRoutingCoordinator(
        orchestrator,
        config,
        price_book=price_book,
        token_counter=HeuristicTokenCounter(tokens_per_word=1.0),
        embedding_batch_backend=backend,
    )

    document = coordinator.complete_embeddings_batch(
        ["one two three four five six seven eight", "short input"],
        model="text-embedding-test",
        attribution={"provider": "acme-provider", "team": "platform"},
    )

    assert len(backend.requests) > 2
    assert all(request.token_count <= 4 for request in backend.requests)
    assert document["part_count"] == len(backend.requests)
    assert document["input_part_counts"][0] > 1
    assert document["input_part_counts"][1] == 1
    assert [item["index"] for item in document["embeddings"]] == [0, 1]

    expected_token_counts = []
    for source_index in range(2):
        expected_token_counts.append(
            sum(request.token_count for request in backend.requests if request.source_index == source_index)
        )
    assert document["token_counts"] == expected_token_counts
    assert document["total_tokens"] == sum(expected_token_counts)

    records = coordinator.ledger.records()
    assert len(records) == 2
    assert all(record["request_channel"] == "batch" for record in records)
    assert all(record["route_mode"] == "embedding" for record in records)


def test_batch_embeddings_char_guard_splits_no_whitespace_input() -> None:
    """The char budget catches inputs a heuristic token counter may undercount."""
    agents = [
        ModelAgent(
            id="mock_worker",
            model="mock-a",
            base_url="mock://a",
            provider_name="mock",
            tags=("reasoning",),
            priority=1,
        )
    ]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    config.set("routing", "embedding_max_tokens_per_request", 100)
    config.set("routing", "embedding_max_chars_per_part", 5)
    backend = _RecordingEmbeddingBackend()
    coordinator = CostRoutingCoordinator(
        orchestrator,
        config,
        token_counter=HeuristicTokenCounter(tokens_per_word=1.0),
        embedding_batch_backend=backend,
    )

    document = coordinator.complete_embeddings_batch(
        ["abcdefghijkl"],
        model="text-embedding-test",
        attribution={"provider": "acme-provider"},
    )

    assert [request.input_text for request in backend.requests] == ["abcde", "fghij", "kl"]
    assert document["part_count"] == 3
    assert document["input_part_counts"] == [3]


def test_batch_embeddings_preserves_per_input_provenance_and_cost_attribution() -> None:
    """Each reduced output keeps the context aligned to its source input index."""
    agents = [
        ModelAgent(
            id="mock_worker",
            model="mock-a",
            base_url="mock://a",
            provider_name="mock",
            tags=("reasoning",),
            priority=1,
        )
    ]
    coordinator = CostRoutingCoordinator(TaskOrchestrator(agents), InMemoryConfigStore())

    document = coordinator.complete_embeddings_batch(
        ["first source", "second source"],
        input_attributions=[{"team": "alpha"}, {"team": "beta"}],
        input_metadata=[{"session_id": "session-a"}, {"session_id": "session-b"}],
    )

    assert [item["index"] for item in document["embeddings"]] == [0, 1]
    assert [item["attribution"]["team"] for item in document["embeddings"]] == [
        "alpha",
        "beta",
    ]
    assert [item["metadata"]["session_id"] for item in document["embeddings"]] == [
        "session-a",
        "session-b",
    ]
    assert [record["team_name"] for record in coordinator.ledger.records()] == [
        "alpha",
        "beta",
    ]
