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
from contextual_orchestrator.chat_capability import (
    is_chat_compatible_model_id,
    is_general_chat_agent_model_id,
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
    price: float,
    *,
    evidence_only: bool = False,
) -> DiscoveredModel:
    """Build one deterministic discovered chat candidate for the tests."""
    return DiscoveredModel(
        provider_name=provider,
        model_id=model,
        credential_name=credential,
        chat_base_url=f"https://{provider}.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=price,
        completion_price_per_1k=price,
        evidence_only=evidence_only,
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
    assert all(agent.tags == ("review",) for agent in orchestrator.agents)
    assert all(get_credential(name) == environment[name] for name in review_gateway.REVIEW_CREDENTIAL_NAMES)


def test_build_review_orchestrator_routes_to_cheapest_selected_agent(monkeypatch):
    """Cost-ranked discovery remains the routing order after agent construction."""
    discovered = [
        _discovered("openai", "expensive_review", "OPENAI_API_KEY", 2.0),
        _discovered("openrouter", "cheap_review", "OPENROUTER_API_KEY", 0.01),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENAI_API_KEY": "openai-secret", "OPENROUTER_API_KEY": "router-secret"},
        max_agents=2,
    )

    assert orchestrator._select_agent("review this change", "worker").model == "cheap_review"


def test_build_review_orchestrator_keeps_provider_diverse_failover(monkeypatch):
    """The gateway uses independently discovered providers before duplicates."""
    discovered = [
        _discovered("openrouter", "cheap_first", "OPENROUTER_API_KEY", 0.01),
        _discovered("openrouter", "cheap_second", "OPENROUTER_API_KEY", 0.02),
        _discovered("openai", "independent_review", "OPENAI_API_KEY", 1.0),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENAI_API_KEY": "openai-secret", "OPENROUTER_API_KEY": "router-secret"},
        max_agents=2,
    )

    assert [agent.model for agent in orchestrator.agents] == [
        "cheap_first",
        "independent_review",
    ]


def test_build_review_orchestrator_never_routes_evidence_only_models(monkeypatch):
    """A row explicitly marked evidence_only is never a review upstream."""
    discovered = [
        _discovered(
            "bytez",
            "router-review",
            "BYTEZ_API_KEY",
            0.01,
            evidence_only=True,
        )
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    with pytest.raises(NotConfigured, match="general chat models"):
        review_gateway.build_review_orchestrator({"BYTEZ_API_KEY": "router-secret"})


def test_build_review_orchestrator_excludes_endpoint_only_models(monkeypatch):
    """Embedding and image catalog rows never enter the review-agent pool."""
    discovered = [
        _discovered("openai", "text-embedding-3-large", "OPENAI_API_KEY", 0.001),
        _discovered("openai", "gpt-review", "OPENAI_API_KEY", 2.0),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENAI_API_KEY": "openai-secret"}, max_agents=1
    )

    assert [agent.model for agent in orchestrator.agents] == ["gpt-review"]


def test_build_review_orchestrator_fails_closed_without_general_chat_models(monkeypatch):
    """A catalog containing only endpoint-specific models cannot start review."""
    discovered = [_discovered("openai", "text-embedding-3-large", "OPENAI_API_KEY", 0.001)]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    with pytest.raises(NotConfigured, match="general chat models"):
        review_gateway.build_review_orchestrator({"OPENAI_API_KEY": "openai-secret"})


@pytest.mark.parametrize(
    ("model_id", "chat_compatible", "general_agent"),
    [
        ("text-embedding-3-large", False, False),
        ("gpt-image-1", False, False),
        ("gpt-review", True, True),
        ("nvidia/llama-3.1-nemoguard-8b-content-safety", True, False),
        (None, False, False),
        ("", False, False),
    ],
)
def test_chat_capability_boundary_is_explicit(
    model_id, chat_compatible: bool, general_agent: bool
) -> None:
    """The gateway rejects endpoint-only and specialized role identifiers."""
    assert is_chat_compatible_model_id(model_id) is chat_compatible
    assert is_general_chat_agent_model_id(model_id) is general_agent


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
        review_gateway.build_review_orchestrator({"OPENAI_API_KEY": "openai-secret"})


def test_build_review_orchestrator_fails_closed_when_selection_is_empty(monkeypatch):
    """A discovery result must still produce at least one selected candidate."""
    monkeypatch.setattr(
        review_gateway,
        "discover_all_models",
        lambda: ([_discovered("openai", "gpt-review", "OPENAI_API_KEY", 0.01)], []),
    )
    monkeypatch.setattr(review_gateway, "select_bootstrap_discovered_agents", lambda *args: [])

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
