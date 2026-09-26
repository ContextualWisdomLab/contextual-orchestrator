"""``timeout=None`` means an unbounded provider-embedding wait, never a crash.

``ModelClient.timeout`` defaults to ``None`` (no implicit deadline, #971), so the
server's ``/v1/embeddings`` handler passes ``wait_timeout=None`` to
``CostRoutingCoordinator.complete_embeddings_batch``, which forwards it to
``ProviderEmbeddingBatchBackend.wait``. That wait must block until the job is
terminal instead of raising ``TypeError`` from ``math.isfinite(None)``.
Everything here is synthetic: provider calls are overridden in-process and
the only socket is the local test server.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from contextual_orchestrator import CostRoutingCoordinator, ModelAgent, TaskOrchestrator
from contextual_orchestrator.batch_routing import (
    EmbeddingBatchRequest,
    ProviderEmbeddingBatchBackend,
)
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.server import SecurityConfig, build_server

_TEST_AUTH_TOKEN = "embeddings_unbounded_wait_token"
_PROVIDER_DELAY_SECONDS = 0.05


class _SyntheticExactCounter:
    def count_text(self, text, model=""):
        """Return a deterministic synthetic authoritative count."""
        return len(text.split())


class _DelayedSyntheticProviderClient(ModelClient):
    """A default ``ModelClient`` (``timeout=None``) whose provider call is local."""

    def __init__(self) -> None:
        super().__init__()
        self.embedding_calls: list[list[str]] = []

    def embed(self, agent, texts):
        time.sleep(_PROVIDER_DELAY_SECONDS)
        self.embedding_calls.append(list(texts))
        return [[float(len(text))] for text in texts]

    def embed_with_usage(self, agent, texts):
        return self.embed(agent, texts), sum(len(text.encode("utf-8")) for text in texts)


def _delayed_runner(requests):
    time.sleep(_PROVIDER_DELAY_SECONDS)
    return [[1.0] for _request in requests], len(requests)


def _submit(backend: ProviderEmbeddingBatchBackend):
    return backend.submit(
        [EmbeddingBatchRequest(input_text="synthetic input", model="synthetic-model")]
    )


def test_backend_wait_with_none_timeout_blocks_until_terminal() -> None:
    backend = ProviderEmbeddingBatchBackend(_delayed_runner)
    try:
        job = _submit(backend)

        status = backend.wait(job, timeout=None)

        assert status["status"] == "completed"
        assert status["is_complete"] is True
    finally:
        backend.close()


def test_backend_wait_still_honours_a_finite_deadline() -> None:
    """``None`` is unbounded; a finite deadline must still return early."""
    release = threading.Event()

    def blocked_runner(requests):
        release.wait(5)
        return [[1.0] for _request in requests], len(requests)

    backend = ProviderEmbeddingBatchBackend(blocked_runner)
    try:
        job = _submit(backend)
        started = time.monotonic()

        status = backend.wait(job, timeout=0.01)

        assert time.monotonic() - started < 2.0
        assert status["is_complete"] is False
    finally:
        release.set()
        backend.close()


def test_backend_wait_with_infinite_timeout_still_blocks_until_terminal() -> None:
    backend = ProviderEmbeddingBatchBackend(_delayed_runner)
    try:
        job = _submit(backend)

        status = backend.wait(job, timeout=float("inf"))

        assert status["status"] == "completed"
    finally:
        backend.close()


def test_complete_embeddings_batch_default_wait_timeout_completes() -> None:
    backend = ProviderEmbeddingBatchBackend(_delayed_runner)
    coordinator = CostRoutingCoordinator(
        TaskOrchestrator([], allow_empty_agents=True),
        embedding_batch_backend=backend,
        embedding_token_counter=_SyntheticExactCounter(),
    )
    try:
        document = coordinator.complete_embeddings_batch(
            ["delayed provider input"], model="synthetic-model"
        )
    finally:
        backend.close()

    assert document["status"] == "completed"
    assert document["embeddings"][0]["embedding"] == [1.0]


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))


def test_default_server_embeddings_path_waits_with_none_timeout(monkeypatch) -> None:
    """Default ``/v1/embeddings`` with a remote member: ``timeout=None`` reaches wait."""
    client = _DelayedSyntheticProviderClient()
    assert client.timeout is None
    agent = ModelAgent(
        "synthetic_embedding",
        "synthetic-embedding-model",
        base_url="https://synthetic.invalid/v1",
        tags=("embedding",),
    )
    orchestrator = TaskOrchestrator([agent], client=client)
    coordinator = CostRoutingCoordinator(
        orchestrator, embedding_token_counter=_SyntheticExactCounter()
    )
    seen_timeouts: list[object] = []
    original_wait = ProviderEmbeddingBatchBackend.wait

    def recording_wait(self, job, *, timeout):
        seen_timeouts.append(timeout)
        return original_wait(self, job, timeout=timeout)

    monkeypatch.setattr(ProviderEmbeddingBatchBackend, "wait", recording_wait)
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            "/v1/embeddings",
            {"model": agent.model, "input": "synthetic text"},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 200, body
    assert body["data"][0]["embedding"] == [14.0]
    assert seen_timeouts == [None]
    assert client.embedding_calls == [["synthetic text"]]
