from __future__ import annotations

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


def test_experiential_labs_free_review_admission_requires_explicit_evidence(monkeypatch):
    """Admit only the explicitly free model and reject paid or unknown pricing."""
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

    orchestrator = review_gateway.build_review_orchestrator({credential_name: "secret"})

    assert [agent.model for agent in orchestrator.agents] == ["experiential/free"]
    assert [agent.credential_key for agent in orchestrator.agents] == [credential_name]
