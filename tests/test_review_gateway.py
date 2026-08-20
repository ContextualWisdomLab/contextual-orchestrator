"""Tests for the trusted CI review gateway bootstrap."""

from __future__ import annotations

import sys

import pytest

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    NotConfigured,
    get_credential,
    set_backend,
)
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator import review_gateway


@pytest.fixture(autouse=True)
def _fresh_backend():
    """Give every gateway test an isolated in-memory credential registry."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _discovered(provider: str, model: str, credential: str, price: float) -> DiscoveredModel:
    """Build one deterministic discovered chat candidate for the tests."""
    return DiscoveredModel(
        provider_name=provider,
        model_id=model,
        credential_name=credential,
        chat_base_url=f"https://{provider}.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=price,
        completion_price_per_1k=price,
    )


def test_build_review_orchestrator_registers_all_provider_credentials(monkeypatch):
    """The bootstrap registers every configured provider key before discovery."""
    discovered = [
        _discovered("openai", "gpt-review", "OPENAI_API_KEY", 0.01),
        _discovered("openrouter", "router-review", "OPENROUTER_API_KEY", 0.02),
        _discovered("nvidia_nim", "nim-review", "NVIDIA_NIM_API_KEY", 0.03),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    environment = {
        name: f"secret-{name.lower()}"
        for name in review_gateway.REVIEW_CREDENTIAL_NAMES
    }

    orchestrator = review_gateway.build_review_orchestrator(environment, max_agents=2)

    assert len(orchestrator.agents) == 2
    assert all(not agent.disabled for agent in orchestrator.agents)
    assert all("review" in agent.tags for agent in orchestrator.agents)
    assert all(get_credential(name) == environment[name] for name in review_gateway.REVIEW_CREDENTIAL_NAMES)


def test_build_review_orchestrator_fails_closed_without_credentials():
    """A sidecar cannot start without at least one registered provider key."""
    with pytest.raises(NotConfigured, match="provider credential"):
        review_gateway.build_review_orchestrator({})


def test_build_review_orchestrator_rejects_invalid_agent_limit():
    """The sidecar refuses an invalid routing-pool bound before using credentials."""
    with pytest.raises(ValueError, match="max_agents"):
        review_gateway.build_review_orchestrator({}, max_agents=0)


def test_build_review_orchestrator_fails_closed_without_discovered_models(monkeypatch):
    """A configured key without a usable model list cannot start the sidecar."""
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: ([], []))
    with pytest.raises(NotConfigured, match="no provider models"):
        review_gateway.build_review_orchestrator({"OPENAI_API_KEY": "openai-secret"})


def test_build_review_orchestrator_fails_closed_when_selection_is_empty(monkeypatch):
    """A discovery result must still produce at least one selected candidate."""
    monkeypatch.setattr(
        review_gateway,
        "discover_all_models",
        lambda: ([_discovered("openai", "gpt-review", "OPENAI_API_KEY", 0.01)], []),
    )
    monkeypatch.setattr(review_gateway, "select_top_n_cheapest_discovered_agents", lambda *args: [])

    with pytest.raises(NotConfigured, match="selected no provider models"):
        review_gateway.build_review_orchestrator({"OPENAI_API_KEY": "openai-secret"})


def test_main_starts_authenticated_gateway(monkeypatch):
    """The CLI passes the generated local token into the protected server."""
    discovered = [_discovered("openai", "gpt-review", "OPENAI_API_KEY", 0.01)]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    captured: dict[str, object] = {}

    def fake_serve(orchestrator, **kwargs):
        """Capture server startup without binding a test port."""
        captured["orchestrator"] = orchestrator
        captured.update(kwargs)

    monkeypatch.setattr(review_gateway, "serve", fake_serve)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", "local-review-token")
    monkeypatch.setattr(sys, "argv", ["review_gateway", "--port", "18181"])

    review_gateway.main()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 18181
    security = captured["security"]
    assert security.auth_token == "local-review-token"
    assert security.allow_public_bind is False


def test_main_requires_authentication(monkeypatch):
    """The sidecar never starts an unauthenticated inference endpoint."""
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["review_gateway"])

    with pytest.raises(SystemExit, match="CONTEXTUAL_ORCHESTRATOR_TOKEN"):
        review_gateway.main()
