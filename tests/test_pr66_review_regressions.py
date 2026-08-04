"""Regression tests for review findings on synchronous embeddings and KV bootstrap."""

from __future__ import annotations

import http.client
import io
import json
from pathlib import Path
import sys
import threading
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    CostRoutingCoordinator,
    ModelAgent,
    TaskOrchestrator,
)
from contextual_orchestrator import __main__ as cli  # noqa: E402
from contextual_orchestrator.batch_routing import (  # noqa: E402
    BatchJob,
    EmbeddingBatchRequest,
    EmbeddingBatchResultItem,
)
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    get_credential,
    set_backend,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_credential_backend():
    """Give every regression test an isolated in-memory credential store."""

    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


class _ReviewEmbeddingBackend:
    """Return deterministic vectors while recording provider-facing metadata."""

    name = "review-backend"

    def __init__(self, *, vector: list[Any], model: str) -> None:
        self.vector = vector
        self.model = model
        self.metadata: dict[str, Any] | None = None
        self._results: list[EmbeddingBatchResultItem] = []

    def submit(
        self,
        requests: list[EmbeddingBatchRequest],
        metadata: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> BatchJob:
        """Record metadata and prepare one deterministic result per request."""

        del timeout_seconds
        request_items = list(requests)
        self.metadata = dict(metadata or {})
        self._results = [
            EmbeddingBatchResultItem(
                custom_id=request.custom_id,
                index=index,
                embedding=list(self.vector),
                prompt_tokens=max(1, request.token_count),
                model=self.model,
            )
            for index, request in enumerate(request_items)
        ]
        return BatchJob(
            job_id="review-embedding-job",
            backend=self.name,
            status="completed",
            request_count=len(request_items),
        )

    def poll(
        self,
        job: BatchJob,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Report the deterministic review job as complete."""

        del timeout_seconds
        return {"job_id": job.job_id, "status": "completed", "is_complete": True}

    def retrieve(
        self,
        job: BatchJob,
        timeout_seconds: float | None = None,
    ) -> list[EmbeddingBatchResultItem]:
        """Return the prepared deterministic results."""

        del job, timeout_seconds
        return list(self._results)


def _orchestrator() -> TaskOrchestrator:
    """Build the smallest deterministic orchestrator accepted by the server."""

    return TaskOrchestrator(
        [ModelAgent(id="mock_worker", model="mock-a", base_url="mock://a")]
    )


def test_register_credential_requires_explicit_value_stdin_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The only supported secret transport must be explicitly selected."""

    monkeypatch.setattr(sys, "stdin", io.StringIO("secret-from-stdin"))

    with pytest.raises(SystemExit):
        cli._register_credential_command(["--name", "REVIEW_API_KEY"])

    assert get_credential("REVIEW_API_KEY") is None

    monkeypatch.setattr(sys, "stdin", io.StringIO("secret-from-stdin"))
    cli._register_credential_command(
        ["--name", "REVIEW_API_KEY", "--value-stdin"]
    )
    assert get_credential("REVIEW_API_KEY") == "secret-from-stdin"


def test_embedding_backend_rejects_boolean_vector_components() -> None:
    """JSON booleans are not numeric embedding components despite Python bool."""

    coordinator = CostRoutingCoordinator(
        _orchestrator(),
        embedding_batch_backend=_ReviewEmbeddingBackend(
            vector=[True, False],
            model="backend-model",
        ),
    )

    document = coordinator.complete_embeddings_sync(
        ["semantic chunk"],
        model="requested-model",
        dimensions=2,
        timeout_seconds=1,
        poll_interval_seconds=0.001,
    )

    assert document["status"] == "failed"
    assert document["error_code"] == "incomplete_embeddings_result"
    assert coordinator.ledger.records() == []


def test_sync_embeddings_uses_backend_model_without_leaking_request_channel() -> None:
    """The HTTP response uses the actual model and provider metadata stays minimal."""

    orchestrator = _orchestrator()
    backend = _ReviewEmbeddingBackend(
        vector=[0.25, 0.75],
        model="backend-actual-model",
    )
    coordinator = CostRoutingCoordinator(
        orchestrator,
        embedding_batch_backend=backend,
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="review-token"),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection(
        "127.0.0.1",
        server.server_address[1],
        timeout=5,
    )
    try:
        payload = json.dumps(
            {
                "model": "requested-model",
                "input": "semantic chunk",
                "dimensions": 2,
            }
        )
        connection.request(
            "POST",
            "/v1/embeddings",
            body=payload,
            headers={
                "authorization": "Bearer review-token",
                "content-type": "application/json",
            },
        )
        response = connection.getresponse()
        document = json.loads(response.read())

        assert response.status == 200, document
        assert document["model"] == "backend-actual-model"
        assert backend.metadata == {"actor_scope": "inference"}
    finally:
        connection.close()
        server.shutdown()
        thread.join(timeout=5)
