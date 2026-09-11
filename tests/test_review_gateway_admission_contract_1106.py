"""Tests for issue #1106: owner-versioned review-pool admission contract.

The free review pool must expose typed, request-scoped provenance so a leaf
caller can send only the gateway token plus ``model: orchestrator/free`` and
delete its own provider/model/credential/probing/admission preflight. These
tests exercise the real contract behavior, not the mere presence of a name.
"""

from __future__ import annotations

from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator import review_gateway

import pytest


@pytest.fixture(autouse=True)
def _fresh_backend():
    """Give each contract test an isolated in-memory credential registry."""
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
    max_output_tokens: int | None = None,
    context_window: int | None = None,
) -> DiscoveredModel:
    """Build one explicitly evidenced, free, text-only chat candidate."""
    return DiscoveredModel(
        provider_name=provider,
        model_id=model,
        credential_name=credential,
        chat_base_url=f"https://{provider}.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=0.0,
        completion_price_per_1k=0.0,
        is_free=True,
        capabilities=("chat",),
        input_modalities=("text",),
        output_modalities=("text",),
        max_output_tokens=max_output_tokens,
        context_window=context_window,
    )


def test_versioned_contract_exposes_real_admission_provenance(monkeypatch):
    """The contract yields typed per-model eligibility evidence, not just a name."""
    discovered = [
        _discovered(
            "openrouter",
            "router-review",
            "OPENROUTER_API_KEY",
            max_output_tokens=8192,
            context_window=131072,
        ),
        _discovered("nvidia_nim", "nim-review", "NVIDIA_NIM_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret", "NVIDIA_NIM_API_KEY": "nim-secret"}
    )

    admissions = review_gateway.review_pool_admissions(orchestrator.agents)

    assert {admission.model_id for admission in admissions} == {
        "router-review",
        "nim-review",
    }
    assert {admission.provider_name for admission in admissions} == {
        "openrouter",
        "nvidia_nim",
    }
    assert {admission.credential_key for admission in admissions} == {
        "OPENROUTER_API_KEY",
        "NVIDIA_NIM_API_KEY",
    }
    assert all(
        admission.contract_version == review_gateway.REVIEW_READINESS_CONTRACT_VERSION
        for admission in admissions
    )
    router = next(a for a in admissions if a.model_id == "router-review")
    assert router.max_output_tokens == 8192
    assert router.context_window == 131072
    assert "cost:free" in router.tags
    assert "review" in router.tags


def test_admission_excludes_openai_source_even_when_discovered(monkeypatch):
    """Typed provenance never carries an OpenAI-sourced model into the pool."""
    discovered = [
        _discovered("openai", "gpt-review", "OPENAI_API_KEY"),
        _discovered("openrouter", "router-review", "OPENROUTER_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENAI_API_KEY": "openai-secret", "OPENROUTER_API_KEY": "router-secret"}
    )

    admissions = review_gateway.review_pool_admissions(orchestrator.agents)

    assert [admission.model_id for admission in admissions] == ["router-review"]
    assert all(admission.provider_name != "openai" for admission in admissions)


def test_single_model_provenance_helper_matches_pool_projection():
    """The per-model helper agrees with the pool projection for one candidate."""
    model = _discovered(
        "openrouter",
        "router-review",
        "OPENROUTER_API_KEY",
        max_output_tokens=4096,
    )
    admission = review_gateway.review_model_admission(
        model, tags=("discovered", "review", "cost:free")
    )
    assert admission.model_id == "router-review"
    assert admission.provider_name == "openrouter"
    assert admission.credential_key == "OPENROUTER_API_KEY"
    assert admission.max_output_tokens == 4096
    assert admission.contract_version == review_gateway.REVIEW_READINESS_CONTRACT_VERSION


def test_client_envelope_rises_to_largest_declared_catalog_maximum(monkeypatch):
    """The envelope is catalog-derived, not a fixed hidden cap."""
    discovered = [
        _discovered(
            "openrouter",
            "small-review",
            "OPENROUTER_API_KEY",
            max_output_tokens=4096,
        ),
        _discovered(
            "openrouter",
            "large-review",
            "OPENROUTER_API_KEY",
            max_output_tokens=200000,
        ),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )
    assert orchestrator.client.max_output_tokens == 200000


def test_client_envelope_uses_documented_fallback_without_catalog_maxima(monkeypatch):
    """With no declared maxima the client uses the documented bootstrap envelope."""
    discovered = [
        _discovered("openrouter", "router-review", "OPENROUTER_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )
    assert (
        orchestrator.client.max_output_tokens
        == review_gateway.REVIEW_OUTPUT_ENVELOPE_FALLBACK
    )
