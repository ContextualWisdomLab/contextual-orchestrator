from __future__ import annotations

from dataclasses import replace

import pytest

from contextual_orchestrator import review_gateway
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend
from contextual_orchestrator.model_discovery import DiscoveredModel


@pytest.fixture(autouse=True)
def isolated_credential_backend():
    """Give each admission test an isolated in-memory credential registry."""
    set_backend(InMemoryCredentialBackend())
    yield
    set_backend(None)


def _discovered_model(credential_name: str, model_id: str, *, token_price: float | None) -> DiscoveredModel:
    """Build a discovered model with explicit pricing evidence for admission."""
    return DiscoveredModel(
        provider_name="experiential_labs",
        model_id=model_id,
        credential_name=credential_name,
        chat_base_url="https://api.experientiallabs.ai/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=token_price,
        completion_price_per_1k=token_price,
        is_free=token_price == 0.0,
        input_modalities=("text",),
        output_modalities=("text",),
    )


def test_experiential_labs_free_review_admission_fails_closed_without_lane_evidence(monkeypatch):
    """Reject promotional zero pricing until free-only enforcement is proven."""
    credential_name = "EXPERIENTAL_LABS_API_KEY"
    discovered = [
        _discovered_model(credential_name, "experiential/free", token_price=0.0),
        _discovered_model(credential_name, "experiential/paid", token_price=1.0),
        _discovered_model(credential_name, "experiential/unknown", token_price=None),
        DiscoveredModel(
            provider_name="openrouter",
            model_id="router/free",
            credential_name="OPENROUTER_API_KEY",
            chat_base_url="https://openrouter.ai/api/v1",
            auth_scheme="Bearer",
            prompt_price_per_1k=0.0,
            completion_price_per_1k=0.0,
            is_free=True,
            input_modalities=("text",),
            output_modalities=("text",),
        ),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    with pytest.raises(review_gateway.NotConfigured, match="no eligible zero-cost"):
        review_gateway.build_review_orchestrator({credential_name: "secret"})


def test_experiential_zdr_admission_requires_model_specific_declared_evidence():
    """Require-ZDR follows declared per-model evidence, not provider attestation."""
    from contextual_orchestrator.model_discovery import agent_from_discovered
    from contextual_orchestrator.orchestrator import TaskOrchestrator

    credential_name = "EXPERIENTAL_LABS_API_KEY"
    models = []
    for model_id, evidence in (
        ("experiential/zdr", True),
        ("experiential/no-zdr", False),
        ("experiential/unknown", None),
    ):
        model = _discovered_model(credential_name, model_id, token_price=0.0)
        model = replace(
            model, supports_zero_data_retention=evidence, zdr_capable=False
        )
        models.append(model)

    agents = [replace(agent_from_discovered(model), disabled=False) for model in models]
    orchestrator = TaskOrchestrator(agents)
    with orchestrator.request_policy(True):
        assert [
            agent.model
            for agent in agents
            if orchestrator._zdr_agent_allowed(agent)
        ] == ["experiential/zdr"]
        assert all(agent.credential_key == credential_name for agent in agents)


def test_experiential_free_tags_cannot_reach_persisted_or_capability_routes():
    """Reject stale promotional free tags at the serving-agent choke point."""
    from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator

    agent = ModelAgent(
        id="experiential_free",
        model="gpt-5.6-luna",
        provider_name="experiential_labs",
        tags=("chat", "cost:free", "embedding"),
    )
    orchestrator = TaskOrchestrator([agent])

    assert orchestrator._is_free_agent(agent) is False
    assert orchestrator._is_general_free_agent(agent) is False
    with pytest.raises(RuntimeError, match="no enabled zero-cost model"):
        orchestrator._capability_agents("embedding", orchestrator.FREE_MODEL)
    assert orchestrator._capability_agents("embedding", agent.model) == [agent]
