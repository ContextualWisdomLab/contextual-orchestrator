"""Review regressions for PR #971 privacy, health, and discovery boundaries."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch

import pytest

from contextual_orchestrator import CostRoutingCoordinator, ModelAgent, TaskOrchestrator
from contextual_orchestrator.batch_routing import EmbeddingBatchRequest
from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.model_discovery import discover_all_models
from contextual_orchestrator.server import SecurityConfig, build_server
from tests.test_model_discovery import OPENAI_SOURCE, OPENROUTER_SOURCE


_AUTH_TOKEN = "pr971_review_quality_token"


def _embedding_coordinator() -> tuple[CostRoutingCoordinator, TaskOrchestrator, ModelAgent]:
    """Build one deterministic ZDR-capable embedding route."""
    agent = ModelAgent(
        "zdr_embedding_agent",
        "embedding-model",
        "https://provider.synthetic.invalid/v1",
        tags=("embedding", "privacy:zdr"),
    )
    orchestrator = TaskOrchestrator([agent])
    orchestrator.client.embed = lambda _agent, texts: [[1.0] for _ in texts]
    coordinator = CostRoutingCoordinator(orchestrator)
    return coordinator, orchestrator, agent


def test_recovered_zdr_batch_reenters_request_privacy_scope(monkeypatch) -> None:
    """Persisted ZDR execution must restore request policy on the worker thread."""
    coordinator, orchestrator, agent = _embedding_coordinator()
    entries: list[bool] = []

    @contextmanager
    def observed_policy(zdr_only: bool):
        entries.append(zdr_only)
        yield

    monkeypatch.setattr(orchestrator, "request_policy", observed_policy)
    coordinator._run_provider_embeddings(
        [
            EmbeddingBatchRequest(
                input_text="private input",
                model=agent.model,
                token_count=2,
                zdr_only=True,
                agent_id=agent.id,
            )
        ]
    )

    assert entries == [True]


def test_provider_embedding_batch_rejects_mixed_privacy_identity() -> None:
    """One coalesced execution cannot mix privacy/routing identities."""
    coordinator, _orchestrator, agent = _embedding_coordinator()
    private = EmbeddingBatchRequest(
        input_text="private",
        model=agent.model,
        token_count=1,
        zdr_only=True,
        agent_id=agent.id,
        provider_routing={"zdr": True},
    )
    ordinary = EmbeddingBatchRequest(
        input_text="ordinary",
        model=agent.model,
        token_count=1,
        zdr_only=False,
        agent_id=agent.id,
        provider_routing=None,
    )

    with pytest.raises(RuntimeError, match="privacy policy"):
        coordinator._run_provider_embeddings([private, ordinary])


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_terminal_embedding_batch_document_fails_over_before_marking_health() -> None:
    """Terminal provider documents are failures, not endpoint-health successes."""
    first = ModelAgent(
        "first_embedding_agent",
        "embed-v1",
        tags=("embedding",),
        priority=1,
    )
    second = ModelAgent(
        "second_embedding_agent",
        "embed-v1",
        tags=("embedding",),
        priority=0,
    )
    orchestrator = TaskOrchestrator([first, second])
    coordinator = CostRoutingCoordinator(orchestrator)
    attempted: list[str] = []

    def complete(_inputs, *, agent_id=None, **_kwargs):
        attempted.append(str(agent_id))
        if agent_id == first.id:
            return {
                "batch_id": "failed-batch",
                "status": "failed",
                "backend": "provider",
                "model": first.model,
                "embeddings": None,
            }
        return {
            "batch_id": "accepted-batch",
            "status": "validating",
            "backend": "provider",
            "model": second.model,
            "embeddings": None,
        }

    coordinator.complete_embeddings_batch = complete
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_AUTH_TOKEN),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            "/v1/batch/embeddings",
            {"model": "embed-v1", "input": "hello"},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 202
    assert body["batch_id"] == "accepted-batch"
    assert attempted == [first.id, second.id]


def _assert_discovery_finishes(call) -> None:
    """Require one discovery call to abandon a hung shared metadata fetch."""
    errors: list[BaseException] = []

    def run() -> None:
        try:
            call()
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=0.5)
    assert not worker.is_alive(), "shared discovery metadata bypassed the discovery deadline"
    assert errors == []


def test_discover_all_models_bounds_every_shared_metadata_fetch() -> None:
    """Models.dev, OpenRouter ZDR, and credit metadata share the control-plane bound."""
    set_backend(InMemoryCredentialBackend())
    try:
        register_credential("OPENAI_API_KEY", "sk-openai")
        never_models_dev = threading.Event()
        source = replace(OPENAI_SOURCE, models_dev_provider_id="openai")
        with (
            patch(
                "contextual_orchestrator.model_discovery._fetch_models_dev_metadata",
                side_effect=lambda **_kwargs: never_models_dev.wait(),
            ),
            patch(
                "contextual_orchestrator.model_discovery.discover_provider_models",
                return_value=[],
            ),
            patch(
                "contextual_orchestrator.model_discovery._openrouter_zdr_model_ids",
                return_value=set(),
            ),
        ):
            _assert_discovery_finishes(
                lambda: discover_all_models((source,), discovery_deadline=0.05)
            )

        set_backend(InMemoryCredentialBackend())
        register_credential("OPENROUTER_API_KEY", "sk-router")
        never_zdr = threading.Event()
        with (
            patch(
                "contextual_orchestrator.model_discovery.discover_provider_models",
                return_value=[],
            ),
            patch(
                "contextual_orchestrator.model_discovery._openrouter_zdr_model_ids",
                side_effect=lambda **_kwargs: never_zdr.wait(),
            ),
            patch(
                "contextual_orchestrator.model_discovery.openrouter_paid_inference_available",
                return_value=None,
            ),
        ):
            _assert_discovery_finishes(
                lambda: discover_all_models((OPENROUTER_SOURCE,), discovery_deadline=0.05)
            )

        never_credit = threading.Event()
        with (
            patch(
                "contextual_orchestrator.model_discovery.discover_provider_models",
                return_value=[],
            ),
            patch(
                "contextual_orchestrator.model_discovery._openrouter_zdr_model_ids",
                return_value=set(),
            ),
            patch(
                "contextual_orchestrator.model_discovery.openrouter_paid_inference_available",
                side_effect=lambda **_kwargs: never_credit.wait(),
            ),
        ):
            _assert_discovery_finishes(
                lambda: discover_all_models((OPENROUTER_SOURCE,), discovery_deadline=0.05)
            )
    finally:
        set_backend(None)
