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


def _discovered(
    provider: str,
    model: str,
    credential: str,
    *,
    is_free: bool = True,
    evidence_only: bool = False,
    capabilities: tuple[str, ...] = ("chat",),
    output_modalities: tuple[str, ...] = ("text",),
) -> DiscoveredModel:
    """Build one explicitly evidenced discovered candidate for the tests."""
    return DiscoveredModel(
        provider_name=provider,
        model_id=model,
        credential_name=credential,
        chat_base_url=f"https://{provider}.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=0.0 if is_free else 1.0,
        completion_price_per_1k=0.0 if is_free else 1.0,
        is_free=is_free,
        evidence_only=evidence_only,
        capabilities=capabilities,
        output_modalities=output_modalities,
    )


def test_build_review_orchestrator_registers_all_credentials_but_serves_free_sources(
    monkeypatch,
):
    """Registration is global while free-pool admission is source constrained."""
    discovered = [
        _discovered("openai", "gpt-review", "OPENAI_API_KEY"),
        _discovered("openrouter", "router-review", "OPENROUTER_API_KEY"),
        _discovered("nvidia_nim", "nim-review", "NVIDIA_NIM_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    environment = {
        name: f"secret-{name.lower()}"
        for name in review_gateway.REVIEW_CREDENTIAL_NAMES
    }

    orchestrator = review_gateway.build_review_orchestrator(environment, max_agents=12)

    assert {agent.credential_key for agent in orchestrator.agents} == {
        "OPENROUTER_API_KEY",
        "NVIDIA_NIM_API_KEY",
    }
    assert all(not agent.disabled for agent in orchestrator.agents)
    assert all("cost:free" in agent.tags for agent in orchestrator.agents)
    assert all(
        get_credential(name) == environment[name]
        for name in review_gateway.REVIEW_CREDENTIAL_NAMES
    )


def test_build_review_orchestrator_rejects_paid_rows(monkeypatch):
    """Provider eligibility cannot override explicit nonzero pricing evidence."""
    discovered = [
        _discovered(
            "openrouter",
            "paid-review",
            "OPENROUTER_API_KEY",
            is_free=False,
        )
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    with pytest.raises(NotConfigured, match="eligible zero-cost"):
        review_gateway.build_review_orchestrator(
            {"OPENROUTER_API_KEY": "router-secret"}
        )


def test_build_review_orchestrator_never_routes_evidence_only_models(monkeypatch):
    """Evidence-only catalog rows are never review upstreams."""
    discovered = [
        _discovered(
            "openrouter",
            "router-review",
            "OPENROUTER_API_KEY",
            evidence_only=True,
        )
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    with pytest.raises(NotConfigured, match="eligible zero-cost"):
        review_gateway.build_review_orchestrator(
            {"OPENROUTER_API_KEY": "router-secret"}
        )


def test_build_review_orchestrator_excludes_explicit_non_chat_models(monkeypatch):
    """Structured capability evidence, not the credential source, governs chat fitness."""
    discovered = [
        _discovered(
            "openrouter",
            "embedding-model",
            "OPENROUTER_API_KEY",
            capabilities=("embeddings",),
            output_modalities=("embedding",),
        ),
        _discovered("openrouter", "review-model", "OPENROUTER_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}, max_agents=12
    )

    assert [agent.model for agent in orchestrator.agents] == ["review-model"]


def test_build_review_orchestrator_fails_closed_without_credentials():
    """A sidecar cannot start without at least one registered provider key."""
    with pytest.raises(NotConfigured, match="provider credential"):
        review_gateway.build_review_orchestrator({})


def test_build_review_orchestrator_does_not_count_auth_as_provider_credential():
    """The gateway auth token cannot satisfy the provider bootstrap gate."""
    with pytest.raises(NotConfigured, match="provider credential"):
        review_gateway.build_review_orchestrator(
            {review_gateway.REVIEW_AUTH_CREDENTIAL_NAME: "local-review-token"}
        )


def test_build_review_orchestrator_rejects_invalid_agent_limit():
    """The sidecar refuses an invalid routing-pool bound before using credentials."""
    with pytest.raises(ValueError, match="max_agents"):
        review_gateway.build_review_orchestrator({}, max_agents=0)


def test_build_review_orchestrator_fails_closed_without_discovered_models(monkeypatch):
    """A configured key without a usable model list cannot start the sidecar."""
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: ([], []))
    with pytest.raises(NotConfigured, match="no provider models"):
        review_gateway.build_review_orchestrator(
            {"OPENROUTER_API_KEY": "router-secret"}
        )


def test_build_review_orchestrator_fails_closed_when_selection_is_empty(monkeypatch):
    """A discovery result must still produce at least one selected candidate."""
    monkeypatch.setattr(
        review_gateway,
        "discover_all_models",
        lambda: (
            [_discovered("openrouter", "review-model", "OPENROUTER_API_KEY")],
            [],
        ),
    )
    monkeypatch.setattr(
        review_gateway, "select_bootstrap_discovered_agents", lambda *args: []
    )

    with pytest.raises(NotConfigured, match="selected no provider models"):
        review_gateway.build_review_orchestrator(
            {"OPENROUTER_API_KEY": "router-secret"}
        )


def test_main_starts_authenticated_gateway(monkeypatch):
    """The CLI passes the generated local token into the protected server."""
    discovered = [
        _discovered("openrouter", "review-model", "OPENROUTER_API_KEY")
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    captured: dict[str, object] = {}

    def fake_serve(orchestrator, **kwargs):
        """Capture server startup without binding a test port."""
        captured["orchestrator"] = orchestrator
        captured.update(kwargs)

    monkeypatch.setattr(review_gateway, "serve", fake_serve)
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", "local-review-token")
    monkeypatch.setattr(sys, "argv", ["review_gateway", "--port", "18181"])

    review_gateway.main()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 18181
    security = captured["security"]
    assert security.auth_token == "local-review-token"
    assert security.allow_public_bind is False
    assert get_credential(review_gateway.REVIEW_AUTH_CREDENTIAL_NAME) == "local-review-token"


def test_main_requires_authentication(monkeypatch):
    """The sidecar never starts an unauthenticated inference endpoint."""
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["review_gateway"])

    with pytest.raises(SystemExit, match="CONTEXTUAL_ORCHESTRATOR_TOKEN"):
        review_gateway.main()


def test_main_rejects_invalid_agent_limit_without_traceback(monkeypatch, capsys):
    """Argparse reports an invalid routing-pool bound as a CLI usage error."""
    monkeypatch.setattr(sys, "argv", ["review_gateway", "--max-agents", "0"])
    with pytest.raises(SystemExit) as exc_info:
        review_gateway.main()
    assert exc_info.value.code == 2
    assert "--max-agents must be a positive integer" in capsys.readouterr().err
