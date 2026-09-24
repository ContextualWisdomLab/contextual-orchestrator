"""Tests for the trusted CI review gateway bootstrap."""

from __future__ import annotations

import logging
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
    input_modalities: tuple[str, ...] = ("text",),
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
        input_modalities=input_modalities,
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

    orchestrator = review_gateway.build_review_orchestrator(environment)

    assert {agent.credential_key for agent in orchestrator.agents} == {
        "OPENROUTER_API_KEY",
        "NVIDIA_NIM_API_KEY",
    }
    assert all(not agent.disabled for agent in orchestrator.agents)
    assert all("cost:free" in agent.tags for agent in orchestrator.agents)
    assert all("input:text" in agent.tags for agent in orchestrator.agents)
    assert all("output:text" in agent.tags for agent in orchestrator.agents)
    assert {agent.priority for agent in orchestrator.agents} == {0}
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
            "bytez",
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
        {"OPENROUTER_API_KEY": "router-secret"}
    )

    assert [agent.model for agent in orchestrator.agents] == ["review-model"]


def test_build_review_orchestrator_excludes_free_multimodal_input_model(monkeypatch):
    """Blind review selection must reuse the general-free modality boundary."""
    discovered = [
        _discovered(
            "openrouter",
            "vision-review-model",
            "OPENROUTER_API_KEY",
            input_modalities=("text", "image"),
        )
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    with pytest.raises(NotConfigured, match="eligible zero-cost"):
        review_gateway.build_review_orchestrator(
            {"OPENROUTER_API_KEY": "router-secret"}
        )


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


def test_build_review_orchestrator_fails_closed_without_discovered_models(monkeypatch):
    """A configured key without a usable model list cannot start the sidecar."""
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: ([], []))
    with pytest.raises(NotConfigured, match="no provider models"):
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


def test_main_configures_redacted_logging_before_discovery(monkeypatch, capsys):
    """INFO sends discovery and request summaries to redacted stderr."""
    discovered = [
        _discovered("openrouter", "review-model", "OPENROUTER_API_KEY")
    ]

    def fake_discover():
        """Emit a discovery record before the server starts."""
        logging.getLogger("contextual_orchestrator.model_discovery").info(
            "discovery_complete token=non-credential-fixture"
        )
        return discovered, []

    monkeypatch.setattr(review_gateway, "discover_all_models", fake_discover)
    monkeypatch.setattr(
        review_gateway,
        "serve",
        lambda orchestrator, **kwargs: logging.getLogger(
            "contextual_orchestrator.server"
        ).info("http_request status=200 latency_ms=1 request_id=test-request"),
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", "local-review-token")
    monkeypatch.setattr(sys, "argv", ["review_gateway", "--log-level", "info"])

    review_gateway.main()

    stderr = capsys.readouterr().err
    assert "discovery_complete token=[REDACTED]" in stderr
    assert "http_request status=200 latency_ms=1 request_id=test-request" in stderr
    assert "non-credential-fixture" not in stderr


def test_main_forwards_repeated_credential_array_to_candidate_scope(monkeypatch):
    """CLI deployments can explicitly constrain the bootstrap provider array."""
    discovered = [
        _discovered("bytez", "bytez-review", "BYTEZ_API_KEY"),
        _discovered("openrouter", "router-review", "OPENROUTER_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    captured: dict[str, object] = {}

    def fake_serve(orchestrator, **kwargs):
        """Capture the CLI-selected serving pool without binding a port."""
        captured["orchestrator"] = orchestrator
        captured.update(kwargs)

    monkeypatch.setattr(review_gateway, "serve", fake_serve)
    monkeypatch.setenv("BYTEZ_API_KEY", "bytez-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", "local-review-token")
    monkeypatch.setattr(
        sys,
        "argv",
        ["review_gateway", "--credential-name", "BYTEZ_API_KEY"],
    )

    review_gateway.main()

    orchestrator = captured["orchestrator"]
    assert [agent.credential_key for agent in orchestrator.agents] == ["BYTEZ_API_KEY"]


def test_main_requires_authentication(monkeypatch):
    """The sidecar never starts an unauthenticated inference endpoint."""
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["review_gateway"])

    with pytest.raises(SystemExit, match="CONTEXTUAL_ORCHESTRATOR_TOKEN"):
        review_gateway.main()


def test_build_review_orchestrator_admits_every_evidence_eligible_candidate(monkeypatch):
    """Review admission cannot evict eligible models through an arbitrary pool cap."""
    discovered = [
        _discovered(
            "openrouter",
            f"review-model-{index:02d}",
            "OPENROUTER_API_KEY",
        )
        for index in range(13)
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )

    assert {agent.model for agent in orchestrator.agents} == {
        model.model_id for model in discovered
    }
    assert len(orchestrator.agents) == len(discovered)
    assert {agent.priority for agent in orchestrator.agents} == {0}


def test_review_gateway_cli_has_no_decision_affecting_model_cap():
    """The trusted sidecar exposes no hand-tuned candidate-count admission control."""
    assert "--max-agents" not in review_gateway._build_parser().format_help()


def test_build_review_orchestrator_sizes_failover_budget_to_the_admitted_pool(monkeypatch):
    """A large free pool must not give up after the generic 2-attempt default.

    ``TaskOrchestrator`` defaults ``tool_retry_attempts`` to 1 (route_once tries
    at most 2 candidates) for every caller. The org's opencode-review-dispatch
    workflow calls ``orchestrator/free`` exactly once per PR review
    (``OPENCODE_MODEL_ATTEMPTS=1``, ``OPENCODE_POOL_MAX_CYCLES=1``) and falls
    back to a model-unavailable evidence-only review on any rejected/failed
    answer. With a dozen-plus discovered free candidates, capping our own
    internal failover at 2 wastes the rest of the catalog and manufactures
    exactly the "gives up after a few shallow attempts" fallback the workflow
    then has to absorb. The failover budget must scale with the admitted pool,
    bounded by the documented hard ceiling.
    """
    from contextual_orchestrator.tool_fallback import MAX_TOOL_RETRY_ATTEMPTS

    discovered = [
        _discovered(
            "openrouter",
            f"review-model-{index:02d}",
            "OPENROUTER_API_KEY",
        )
        for index in range(13)
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )

    assert orchestrator.tool_retry_attempts == MAX_TOOL_RETRY_ATTEMPTS


def test_build_review_orchestrator_never_exceeds_a_small_pool(monkeypatch):
    """The failover budget cannot exceed the number of candidates actually admitted."""
    discovered = [_discovered("openrouter", "solo-review", "OPENROUTER_API_KEY")]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )

    assert orchestrator.tool_retry_attempts == 0
