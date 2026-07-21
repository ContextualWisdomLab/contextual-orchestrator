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

import asyncio
from pathlib import Path
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
    EmbeddingSubmissionTimeout,
    LocalEmbeddingBatchBackend,
    PgLlmBatchEmbeddingBackend,
    heuristic_embedding,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402
from contextual_orchestrator.token_counting import HeuristicTokenCounter  # noqa: E402


CONTRACT = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "batch_embeddings_contract.json").read_text(
        encoding="utf-8"
    )
)


def _serve():
    agents = [
        ModelAgent(
            id="mock_worker",
            model="mock-a",
            base_url="mock://a",
            provider_name="mock",
            tags=("reasoning", "coding", "writing"),
            priority=1,
        )
    ]
    orchestrator = TaskOrchestrator(agents)
    config = InMemoryConfigStore()
    price_book = PriceBook(config)
    # Price the embeddings provider so cost is a real, non-zero number.
    price_book.set_price(
        PriceEntry("acme-provider", "text-embedding-test", prompt_price_per_1k=0.13, completion_price_per_1k=0.0)
    )
    coordinator = CostRoutingCoordinator(orchestrator, config, price_book=price_book)
    token = "cost_token"
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=token), coordinator=coordinator
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1], token, coordinator


def _request(method, url, token=None, body=None):
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:  # pragma: no cover - surfaced in asserts
        return exc.code, json.loads(exc.read())


class _RecordingEmbeddingBackend:
    """Embedding backend that records the exact mapped requests it receives."""

    name = "recording"

    def __init__(self) -> None:
        self.requests: list[EmbeddingBatchRequest] = []
        self._results: list[EmbeddingBatchResultItem] = []

    def submit(self, requests, metadata=None, timeout_seconds=None):
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

    def poll(self, job, timeout_seconds=None):
        return {"job_id": job.job_id, "status": "completed", "is_complete": True}

    def retrieve(self, job, timeout_seconds=None):
        return list(self._results)


class _DelayedEmbeddingBackend(_RecordingEmbeddingBackend):
    """Fake async backend that becomes complete on its second poll."""

    def __init__(self) -> None:
        super().__init__()
        self.poll_count = 0

    def submit(self, requests, metadata=None, timeout_seconds=None):
        job = super().submit(requests, metadata, timeout_seconds)
        job.status = "submitted"
        return job

    def poll(self, job, timeout_seconds=None):
        self.poll_count += 1
        complete = self.poll_count >= 2
        return {
            "job_id": job.job_id,
            "status": "completed" if complete else "in_progress",
            "is_complete": complete,
        }


class _IncompleteEmbeddingBackend(_RecordingEmbeddingBackend):
    def retrieve(self, job, timeout_seconds=None):
        return super().retrieve(job, timeout_seconds)[:-1]


class _SlowSubmitEmbeddingBackend(_RecordingEmbeddingBackend):
    def submit(self, requests, metadata=None, timeout_seconds=None):
        if timeout_seconds is not None and timeout_seconds < 0.2:
            time.sleep(min(timeout_seconds / 10, 0.001))
            raise TimeoutError("submission deadline exceeded")
        time.sleep(0.2)
        return super().submit(requests, metadata, timeout_seconds)


class _NeverCompletesEmbeddingBackend(_RecordingEmbeddingBackend):
    def submit(self, requests, metadata=None, timeout_seconds=None):
        job = super().submit(requests, metadata, timeout_seconds)
        job.status = "submitted"
        return job

    def poll(self, job, timeout_seconds=None):
        return {"job_id": job.job_id, "status": "in_progress", "is_complete": False}


class _AmbiguousSubmitEmbeddingBackend(_RecordingEmbeddingBackend):
    def submit(self, requests, metadata=None, timeout_seconds=None):
        raise EmbeddingSubmissionTimeout("embsub_recoverable")


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


def test_sync_embeddings_endpoint_returns_openai_compatible_document() -> None:
    """Interactive callers receive vectors without understanding batch jobs."""
    server, port, token, coordinator = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, document = _request(
            "POST",
            f"{base}/v1/embeddings",
            token,
            {
                "model": "text-embedding-test",
                "input": ["first semantic chunk", "second semantic chunk"],
                "dimensions": 128,
                "metadata": {
                    "service": "semantic-data-portal",
                    "provider": "acme-provider",
                },
            },
        )

        assert status == 200, document
        assert document["object"] == "list"
        assert document["model"] == "text-embedding-test"
        assert [item["index"] for item in document["data"]] == [0, 1]
        assert all(item["object"] == "embedding" for item in document["data"])
        assert all(len(item["embedding"]) == 128 for item in document["data"])
        assert document["usage"]["prompt_tokens"] > 0
        assert document["usage"]["total_tokens"] == document["usage"]["prompt_tokens"]
        assert document["orchestration"]["batch_id"]
        assert document["orchestration"]["cost_micro_usd"] > 0
        records = coordinator.ledger.records()
        assert len(records) == 2
        assert all(record["request_channel"] == "sync" for record in records)
    finally:
        server.shutdown()


def test_sync_embeddings_waits_for_an_async_batch_backend() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a")]
    )
    backend = _DelayedEmbeddingBackend()
    coordinator = CostRoutingCoordinator(
        orchestrator,
        embedding_batch_backend=backend,
    )

    document = coordinator.complete_embeddings_sync(
        ["semantic chunk"],
        model="text-embedding-test",
        timeout_seconds=1,
        poll_interval_seconds=0.001,
    )

    assert document["status"] == "completed"
    assert document["embeddings"][0]["embedding"]
    assert backend.poll_count == 2


def test_sync_embeddings_rejects_partial_backend_results_without_recording_cost() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a")]
    )
    backend = _IncompleteEmbeddingBackend()
    coordinator = CostRoutingCoordinator(orchestrator, embedding_batch_backend=backend)

    document = coordinator.complete_embeddings_sync(
        ["first", "second"],
        model="text-embedding-test",
        timeout_seconds=1,
        poll_interval_seconds=0.001,
    )

    assert document["status"] == "failed"
    assert document["error_code"] == "incomplete_embeddings_result"
    assert coordinator.ledger.records() == []


def test_sync_embeddings_timeout_starts_before_submission_and_returns_promptly() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a")]
    )
    coordinator = CostRoutingCoordinator(
        orchestrator,
        embedding_batch_backend=_SlowSubmitEmbeddingBackend(),
    )

    started = time.monotonic()
    document = coordinator.complete_embeddings_sync(
        ["semantic chunk"],
        timeout_seconds=0.02,
        poll_interval_seconds=0.001,
    )

    assert time.monotonic() - started < 0.15
    assert document["status"] == "timed_out"
    assert document["batch_id"] is None
    assert document["reconciliation_required"] is False


def test_local_custom_embedder_must_accept_cooperative_deadline() -> None:
    backend = LocalEmbeddingBatchBackend(embedder=lambda text: [1.0, 0.0])

    with pytest.raises(TypeError, match="timeout_seconds"):
        backend.submit(
            [EmbeddingBatchRequest(input_text="semantic chunk")],
            timeout_seconds=0.1,
        )


def test_pg_embedding_submit_timeout_returns_recoverable_submission_id() -> None:
    class AcceptedButResponseLostClient:
        def __init__(self):
            self.metadata = None

        async def upload_jsonl(self, file_path, endpoint_alias):
            return {"id": "file-accepted"}

        async def create_batch_job(
            self,
            input_file_id,
            endpoint_alias,
            endpoint="/v1/embeddings",
            metadata=None,
        ):
            self.metadata = metadata
            await asyncio.sleep(1)
            return {"id": "batch-late", "status": "validating"}

    client = AcceptedButResponseLostClient()
    backend = PgLlmBatchEmbeddingBackend(client)

    with pytest.raises(EmbeddingSubmissionTimeout) as caught:
        backend.submit(
            [EmbeddingBatchRequest(input_text="semantic chunk")],
            timeout_seconds=0.01,
        )

    assert caught.value.submission_id
    assert client.metadata["orchestrator_submission_id"] == caught.value.submission_id
    assert backend.submission_status(caught.value.submission_id)["status"] == "uncertain"


def test_sync_embeddings_surfaces_ambiguous_submission_for_reconciliation() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a")]
    )
    coordinator = CostRoutingCoordinator(
        orchestrator,
        embedding_batch_backend=_AmbiguousSubmitEmbeddingBackend(),
    )

    document = coordinator.complete_embeddings_sync(["semantic chunk"])

    assert document["status"] == "timed_out"
    assert document["submission_id"] == "embsub_recoverable"
    assert document["reconciliation_required"] is True


def test_sync_embeddings_preserves_submitted_job_for_batch_reconciliation() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a")]
    )
    coordinator = CostRoutingCoordinator(
        orchestrator,
        embedding_batch_backend=_NeverCompletesEmbeddingBackend(),
    )

    document = coordinator.complete_embeddings_sync(
        ["semantic chunk"],
        timeout_seconds=0.01,
        poll_interval_seconds=0.001,
    )

    assert document["status"] == "timed_out"
    assert document["batch_id"]
    assert document["reconciliation_required"] is True
    assert coordinator.embeddings_batch_document(document["batch_id"])["status"] == "in_progress"


def test_embedding_request_jsonl_forwards_requested_dimensions() -> None:
    request = EmbeddingBatchRequest(
        input_text="semantic chunk",
        model="text-embedding-test",
        dimensions=128,
    )

    assert request.to_jsonl_line()["body"]["dimensions"] == 128


def test_sync_embeddings_rejects_invalid_dimensions() -> None:
    server, port, token, _coordinator = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, document = _request(
            "POST",
            f"{base}/v1/embeddings",
            token,
            {"input": "semantic chunk", "dimensions": 0},
        )
        assert status == 400
        assert document["error"]["code"] == "invalid_dimensions"
    finally:
        server.shutdown()


def test_sync_embeddings_rejects_dimensions_above_configured_limit() -> None:
    server, port, token, _coordinator = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, document = _request(
            "POST",
            f"{base}/v1/embeddings",
            token,
            {"input": "semantic chunk", "dimensions": 3073},
        )
        assert status == 400
        assert document["error"]["code"] == "invalid_dimensions"
    finally:
        server.shutdown()


def test_heuristic_embedding_checks_deadline_during_generation() -> None:
    with pytest.raises(TimeoutError, match="deadline"):
        heuristic_embedding("semantic chunk", 128, deadline=time.monotonic() - 1)


def test_sync_embeddings_requires_inference_bearer_token() -> None:
    server, port, _token, _coordinator = _serve()
    base = f"http://127.0.0.1:{port}"
    try:
        status, document = _request(
            "POST",
            f"{base}/v1/embeddings",
            body={"input": "semantic chunk"},
        )
        assert status == 401
        assert document["error"]["code"] == "unauthorized"
    finally:
        server.shutdown()


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
