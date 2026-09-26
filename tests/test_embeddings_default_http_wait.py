"""HTTP and finite-deadline contracts carried from predecessor PR #1269."""

from __future__ import annotations

import threading
import time

from contextual_orchestrator.batch_routing import (
    EmbeddingBatchRequest,
    ProviderEmbeddingBatchBackend,
)


def _submit(backend: ProviderEmbeddingBatchBackend):
    return backend.submit(
        [EmbeddingBatchRequest(input_text="synthetic input", model="synthetic-model")]
    )


def test_finite_provider_embedding_wait_returns_before_terminal() -> None:
    """A finite caller deadline remains bounded while the provider is blocked."""
    release = threading.Event()

    def runner(requests):
        release.wait(timeout=2)
        return [[1.0] for _request in requests], len(requests)

    backend = ProviderEmbeddingBatchBackend(runner)
    try:
        job = _submit(backend)
        started = time.monotonic()

        status = backend.wait(job, timeout=0.01)

        assert time.monotonic() - started < 1
        assert status["is_complete"] is False
    finally:
        release.set()
        backend.close()


def test_default_http_embeddings_path_preserves_none_wait(monkeypatch) -> None:
    """The default HTTP path passes the no-implicit-deadline value unchanged."""
    import json
    import urllib.request

    from contextual_orchestrator import (
        CostRoutingCoordinator,
        ModelAgent,
        TaskOrchestrator,
    )
    from contextual_orchestrator.orchestrator import ModelClient
    from contextual_orchestrator.server import SecurityConfig, build_server

    class SyntheticCounter:
        def count_text(self, text, model=""):
            return len(text.split())

    class SyntheticClient(ModelClient):
        def __init__(self) -> None:
            super().__init__()
            self.embedding_calls = []

        def embed(self, agent, texts):
            self.embedding_calls.append(list(texts))
            return [[float(len(text))] for text in texts]

        def embed_with_usage(self, agent, texts):
            return self.embed(agent, texts), sum(
                len(text.encode("utf-8")) for text in texts
            )

    client = SyntheticClient()
    assert client.timeout is None
    agent = ModelAgent(
        "synthetic_embedding",
        "synthetic-embedding-model",
        base_url="https://synthetic.invalid/v1",
        tags=("embedding",),
    )
    orchestrator = TaskOrchestrator([agent], client=client)
    coordinator = CostRoutingCoordinator(
        orchestrator, embedding_token_counter=SyntheticCounter()
    )
    seen_timeouts = []
    original_wait = ProviderEmbeddingBatchBackend.wait

    def recording_wait(self, job, *, timeout):
        seen_timeouts.append(timeout)
        return original_wait(self, job, timeout=timeout)

    monkeypatch.setattr(ProviderEmbeddingBatchBackend, "wait", recording_wait)
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token="embedding-wait-token"),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/v1/embeddings",
        data=json.dumps({"model": agent.model, "input": "synthetic text"}).encode(),
        headers={
            "content-type": "application/json",
            "authorization": "Bearer embedding-wait-token",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = response.status
            body = json.loads(response.read().decode())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 200, body
    assert body["data"][0]["embedding"] == [14.0]
    assert seen_timeouts == [None]
    assert client.embedding_calls == [["synthetic text"]]
