"""Focused branch coverage for provider-catalog boundary helpers."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextual_orchestrator.provider_catalog as catalog  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelAgent  # noqa: E402


@pytest.fixture(autouse=True)
def _credential_backend():
    """Use one isolated credential registry for every focused branch test."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def test_provider_account_can_explicitly_disable_catalog_discovery() -> None:
    """An account without a listing endpoint advertises no models URL."""
    account = catalog.ProviderAccount(
        "custom_provider",
        "custom_provider",
        "CUSTOM_PROVIDER_KEY",
        "https://models.example",
        models_path=None,
    )
    assert account.models_url is None
    client = catalog.ProviderCatalogHttpClient()
    with pytest.raises(catalog.CatalogHttpError, match="catalog_endpoint_not_configured"):
        client.discover(account, "credential")


def test_http_limit_validation_and_deadline_failure() -> None:
    """Invalid limits and an exhausted wall-clock deadline fail before network access."""
    for options in (
        {"timeout_seconds": 0},
        {"max_attempts": 0},
        {"deadline_seconds": 0},
    ):
        with pytest.raises(ValueError, match="limits must be positive"):
            catalog.ProviderCatalogHttpClient(**options)

    ticks = iter((10.0, 11.0))
    client = catalog.ProviderCatalogHttpClient(deadline_seconds=0.5, clock=lambda: next(ticks))
    with pytest.raises(catalog.CatalogHttpError, match="catalog_deadline_exceeded"):
        client.discover(catalog.DEFAULT_PROVIDER_ACCOUNTS[0], "credential")


def test_http_attempts_exhausted_guard_is_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defensive post-loop guard retains a stable secret-free error code."""
    client = catalog.ProviderCatalogHttpClient()
    monkeypatch.setattr(catalog, "range", lambda _count: [], raising=False)
    with pytest.raises(catalog.CatalogHttpError, match="catalog_attempts_exhausted"):
        client.discover(catalog.DEFAULT_PROVIDER_ACCOUNTS[0], "credential")


def test_model_normalization_covers_specialized_capabilities_and_bad_values() -> None:
    """Reranking, moderation, audio, guard, and malformed metadata stay deterministic."""
    models = catalog.normalize_models_document(
        {
            "data": [
                {"id": "rank/rerank-large"},
                {"id": "safe/moderation-latest"},
                {"id": "voice/whisper-audio", "modalities": "audio"},
                {"id": "secure/guard-model"},
                {
                    "id": "invalid-metadata",
                    "context_length": object(),
                    "pricing": {"prompt": object(), "completion": True},
                    "capabilities": ["", 7, "x" * 129, "CUSTOM"],
                },
                {"id": "x" * 513},
            ]
        }
    )
    by_name = {model.model_name: model for model in models}
    assert by_name["rank/rerank-large"].capabilities == ("reranking",)
    assert by_name["safe/moderation-latest"].capabilities == ("moderation",)
    assert by_name["voice/whisper-audio"].capabilities == ("audio", "chat")
    assert by_name["secure/guard-model"].capabilities == ("chat", "moderation")
    invalid = by_name["invalid-metadata"]
    assert invalid.capabilities == ("chat", "custom")
    assert invalid.context_window is None
    assert invalid.input_price_usd_per_million is None
    assert invalid.output_price_usd_per_million is None
    assert len(by_name) == 5


def test_candidate_tags_cover_multimodal_and_empty_slug_fallback() -> None:
    """Multimodal role tags and hostile model identifiers produce valid agent records."""
    account = catalog.DEFAULT_PROVIDER_ACCOUNTS[4]
    store = catalog.InMemoryProviderCatalogStore()
    store.replace_catalog(
        account,
        [
            catalog.DiscoveredModel(
                model_name="!!!",
                display_name="Punctuation",
                capabilities=("chat", "coding", "vision", "audio"),
                modalities=("audio", "image", "text"),
                context_window=300_000,
                input_price_usd_per_million=0.0,
                output_price_usd_per_million=0.0,
            )
        ],
    )
    agent = catalog.ProviderCatalogService(store=store, accounts=(account,)).candidate_agents()[0]
    assert "model_worker" in agent.id
    assert {"implementation", "debugging", "image", "speech", "multimodal"}.issubset(agent.tags)
    assert agent.priority == account.priority_rank + 5


def test_empty_catalog_factory_fails_closed() -> None:
    """Runtime construction never falls back to an implicit mock worker."""
    with pytest.raises(catalog.ProviderCatalogUnavailable, match="no enabled agents"):
        catalog.build_catalog_orchestrator(catalog.InMemoryProviderCatalogStore())


def test_bytez_string_output_streaming_and_passthrough_guard() -> None:
    """Native Bytez text can be framed, while unsupported passthrough fails closed."""
    account = catalog.DEFAULT_PROVIDER_ACCOUNTS[2]
    catalog.bootstrap_provider_credentials(
        {account.credential_name: "bytez-secret"},
        require_all=False,
        accounts=(account,),
    )
    agent = ModelAgent(
        "bytez_worker",
        "owner/model",
        account.base_url,
        credential_key=account.credential_name,
        provider_name="bytez",
    )
    client = catalog.ProviderAwareModelClient(
        bytez_request=lambda _agent, _messages, _credential: {"output": "native-answer"}
    )
    assert "".join(client.stream_chat(agent, [{"role": "user", "content": "hello"}])) == "native-answer"
    with pytest.raises(catalog.ProviderCatalogUnavailable, match="does not support passthrough"):
        client.proxy_send(agent, "/responses", {})


def test_non_bytez_stream_and_proxy_keep_existing_mock_behavior() -> None:
    """Provider-aware delegation preserves the existing mock transport surfaces."""
    client = catalog.ProviderAwareModelClient()
    agent = ModelAgent("general_agent", "mock-generalist", "mock://local")
    chunks = list(client.stream_chat(agent, [{"role": "user", "content": "hello"}]))
    assert "".join(chunks)
    raw = client.proxy_send(agent, "/responses", {"input": "hello"})
    assert isinstance(raw, dict)


def test_scalar_capability_and_extreme_context_helpers() -> None:
    """Scalar provider metadata and oversized integer values are bounded."""
    model = catalog.normalize_models_document(
        {
            "data": [
                {
                    "id": "custom-model",
                    "capabilities": "SPECIAL",
                    "context_length": "10000000001",
                    "pricing": {"prompt": "not-a-number"},
                }
            ]
        }
    )[0]
    assert model.capabilities == ("chat", "special")
    assert model.context_window is None
    assert model.input_price_usd_per_million is None
