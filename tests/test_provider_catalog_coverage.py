"""Focused branch coverage for provider catalog boundary behavior."""

from __future__ import annotations

from datetime import datetime, timezone
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
    """Use a fresh credential backend for every edge-case test."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def test_account_without_catalog_endpoint_fails_before_network_access() -> None:
    """An explicitly unsupported listing endpoint has a stable permanent code."""
    account = catalog.ProviderAccount(
        "custom_provider",
        "custom_provider",
        "CUSTOM_PROVIDER_KEY",
        "https://provider.example",
        models_path=None,
    )
    assert account.models_url is None
    with pytest.raises(catalog.CatalogHttpError, match="catalog_endpoint_not_configured"):
        catalog.ProviderCatalogHttpClient().discover(account, "credential")


def test_http_client_validates_limits_deadline_and_defensive_post_loop_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid budgets and exhausted control-flow guards fail deterministically."""
    for options in (
        {"timeout_seconds": 0},
        {"max_attempts": 0},
        {"deadline_seconds": 0},
    ):
        with pytest.raises(ValueError, match="limits must be positive"):
            catalog.ProviderCatalogHttpClient(**options)

    ticks = iter((10.0, 11.0))
    deadline_client = catalog.ProviderCatalogHttpClient(
        deadline_seconds=0.5,
        clock=lambda: next(ticks),
    )
    with pytest.raises(catalog.CatalogHttpError, match="catalog_deadline_exceeded"):
        deadline_client.discover(catalog.DEFAULT_PROVIDER_ACCOUNTS[0], "credential")

    guard_client = catalog.ProviderCatalogHttpClient()
    monkeypatch.setattr(catalog, "range", lambda _count: [], raising=False)
    with pytest.raises(catalog.CatalogHttpError, match="catalog_attempts_exhausted"):
        guard_client.discover(catalog.DEFAULT_PROVIDER_ACCOUNTS[0], "credential")


def test_retry_uses_jitter_then_honors_bounded_retry_after() -> None:
    """Transient errors retry within the policy and never sleep beyond the cap."""
    sleeps: list[float] = []
    client = catalog.ProviderCatalogHttpClient(
        max_attempts=3,
        sleep=sleeps.append,
        random_uniform=lambda _low, high: high,
        clock=lambda: 0.0,
    )
    calls: list[int] = []

    def request(_account, _credential):
        calls.append(1)
        if len(calls) == 1:
            raise catalog.CatalogHttpError("catalog_http_503", transient=True)
        if len(calls) == 2:
            raise catalog.CatalogHttpError(
                "catalog_http_429",
                transient=True,
                retry_after_seconds=300.0,
            )
        return {"data": [{"id": "meta-llama/llama-instruct"}]}

    client._request_json = request  # type: ignore[method-assign]
    models = client.discover(catalog.DEFAULT_PROVIDER_ACCOUNTS[0], "credential")
    assert [model.model_name for model in models] == ["meta-llama/llama-instruct"]
    assert sleeps == [0.5, catalog.MAX_RETRY_AFTER_SECONDS]


def test_retry_skips_zero_delay_and_terminal_permanent_or_transient_errors() -> None:
    """No-op delays are not slept and terminal attempts preserve the stable code."""
    sleeps: list[float] = []
    client = catalog.ProviderCatalogHttpClient(
        max_attempts=2,
        sleep=sleeps.append,
        random_uniform=lambda _low, _high: 0.0,
        clock=lambda: 0.0,
    )
    calls = 0

    def transient_then_success(_account, _credential):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise catalog.CatalogHttpError("catalog_network_failure", transient=True)
        return {"data": [{"id": "qwen-instruct"}]}

    client._request_json = transient_then_success  # type: ignore[method-assign]
    assert client.discover(catalog.DEFAULT_PROVIDER_ACCOUNTS[0], "credential")
    assert sleeps == []

    client._request_json = lambda _account, _credential: (_ for _ in ()).throw(  # type: ignore[method-assign]
        catalog.CatalogHttpError("catalog_authentication_failed")
    )
    with pytest.raises(catalog.CatalogHttpError, match="catalog_authentication_failed"):
        client.discover(catalog.DEFAULT_PROVIDER_ACCOUNTS[0], "credential")

    one_attempt = catalog.ProviderCatalogHttpClient(max_attempts=1)
    one_attempt._request_json = lambda _account, _credential: (_ for _ in ()).throw(  # type: ignore[method-assign]
        catalog.CatalogHttpError("catalog_http_503", transient=True)
    )
    with pytest.raises(catalog.CatalogHttpError, match="catalog_http_503"):
        one_attempt.discover(catalog.DEFAULT_PROVIDER_ACCOUNTS[0], "credential")


def test_empty_successful_document_fails_fast() -> None:
    """A structurally valid but empty listing cannot erase prior service evidence."""
    client = catalog.ProviderCatalogHttpClient(max_attempts=3)
    client._request_json = lambda _account, _credential: {"data": []}  # type: ignore[method-assign]
    with pytest.raises(catalog.CatalogHttpError, match="catalog_contains_no_models"):
        client.discover(catalog.DEFAULT_PROVIDER_ACCOUNTS[0], "credential")


def test_retry_after_parser_accepts_delta_date_and_rejects_malformed_values() -> None:
    """Both RFC forms are bounded and malformed input produces no delay authority."""
    reference = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
    assert catalog._parse_retry_after(None, now=reference) is None
    assert catalog._parse_retry_after("", now=reference) is None
    assert catalog._parse_retry_after("5", now=reference) == 5.0
    assert catalog._parse_retry_after("999", now=reference) == catalog.MAX_RETRY_AFTER_SECONDS
    assert catalog._parse_retry_after(
        "Sun, 16 Aug 2026 00:00:12 GMT",
        now=reference,
    ) == 12.0
    assert catalog._parse_retry_after(
        "Sun, 16 Aug 2026 00:01:00 GMT",
        now=reference,
    ) == catalog.MAX_RETRY_AFTER_SECONDS
    assert catalog._parse_retry_after(
        "Sat, 15 Aug 2026 23:59:59 GMT",
        now=reference,
    ) == 0.0
    assert catalog._parse_retry_after("not-a-date", now=reference) is None


def test_normalizer_covers_specialized_families_explicit_metadata_and_bad_values() -> None:
    """Non-chat families stay out of the serving pool and malformed evidence stays null."""
    models = catalog.normalize_models_document(
        {
            "data": [
                {"id": "rank/rerank-large"},
                {"id": "safe/moderation-latest"},
                {"id": "voice/whisper-transcription"},
                {"id": "voice/tts-model"},
                {"id": "video/sora-model"},
                {"id": "vision/stable-diffusion"},
                {"id": "custom-model", "capabilities": "SPECIAL"},
                {
                    "id": "invalid-metadata",
                    "context_length": True,
                    "pricing": {"prompt": False, "completion": object()},
                    "capabilities": ["", 7, "x" * 129, "CUSTOM"],
                },
            ]
        }
    )
    by_name = {model.model_name: model for model in models}
    assert by_name["rank/rerank-large"].capabilities == ("reranking",)
    assert by_name["safe/moderation-latest"].capabilities == ("moderation",)
    assert by_name["voice/whisper-transcription"].capabilities == ("transcription",)
    assert by_name["voice/tts-model"].capabilities == ("speech_generation",)
    assert by_name["video/sora-model"].capabilities == ("video_generation",)
    assert by_name["vision/stable-diffusion"].capabilities == ("image_generation",)
    assert by_name["custom-model"].capabilities == ("special",)
    invalid = by_name["invalid-metadata"]
    assert invalid.capabilities == ("custom",)
    assert invalid.context_window is None
    assert invalid.input_price_usd_per_million is None
    assert invalid.output_price_usd_per_million is None


def test_chat_capability_enrichment_and_agent_tags_cover_multimodal_roles() -> None:
    """Reasoning/coding/vision/audio hints enrich only an explicitly chat-capable model."""
    model = catalog.normalize_models_document(
        {
            "data": [
                {
                    "id": "gpt-coder-reasoning-vision",
                    "capabilities": ["chat"],
                    "modalities": ["text", "image", "audio"],
                    "context_length": 500_000,
                    "pricing": {"prompt": "0", "completion": "0"},
                }
            ]
        }
    )[0]
    assert model.capabilities == ("audio", "chat", "coding", "reasoning", "vision")
    account = catalog.DEFAULT_PROVIDER_ACCOUNTS[4]
    store = catalog.InMemoryProviderCatalogStore()
    store.replace_catalog(account, [model])
    agent = catalog.ProviderCatalogService(store=store, accounts=(account,)).candidate_agents()[0]
    assert {
        "implementation",
        "debugging",
        "planning",
        "verification",
        "image",
        "speech",
        "multimodal",
    }.issubset(agent.tags)
    assert agent.priority == account.priority_rank + 3


def test_hostile_model_identifier_uses_valid_fallback_agent_slug() -> None:
    """Punctuation-only provider ids still produce governed two-word snake-case ids."""
    account = catalog.DEFAULT_PROVIDER_ACCOUNTS[0]
    store = catalog.InMemoryProviderCatalogStore()
    store.replace_catalog(
        account,
        [catalog.DiscoveredModel("!!!", "Punctuation", ("chat",))],
    )
    agent = catalog.ProviderCatalogService(store=store, accounts=(account,)).candidate_agents()[0]
    assert "model_worker" in agent.id


def test_empty_catalog_factory_and_unknown_provider_record_fail_closed() -> None:
    """Runtime construction and orphaned database rows never invent account authority."""
    with pytest.raises(catalog.ProviderCatalogUnavailable, match="no enabled chat-capable agents"):
        catalog.build_catalog_orchestrator(catalog.InMemoryProviderCatalogStore())

    class _OrphanStore(catalog.InMemoryProviderCatalogStore):
        def enabled_models(self):
            return [
                catalog.CatalogModelRecord(
                    "orphan_account",
                    catalog.DiscoveredModel("qwen-instruct", "Qwen", ("chat",)),
                )
            ]

    assert catalog.ProviderCatalogService(
        store=_OrphanStore(),
        accounts=(),
    ).candidate_agents() == []


def test_bytez_output_variants_streaming_and_text_validation() -> None:
    """Conservative native outputs work while malformed messages remain blocked."""
    account = catalog.DEFAULT_PROVIDER_ACCOUNTS[2]
    catalog.bootstrap_provider_credentials(
        {account.credential_name: "secret"},
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
    outputs = iter(
        (
            {"output": "direct"},
            {"output": {"content": "content"}},
            {"output": {"text": "text"}},
            {"output": [{"generated_text": "list-text"}]},
            {"generated_text": "top-level"},
        )
    )
    client = catalog.ProviderAwareModelClient(
        bytez_request=lambda _agent, _prompt, _credential: next(outputs)
    )
    messages = [{"role": "user", "content": "hello"}]
    assert client.chat(agent, messages) == "direct"
    assert client.chat(agent, messages) == "content"
    assert client.chat(agent, messages) == "text"
    assert client.chat(agent, messages) == "list-text"
    assert "".join(client.stream_chat(agent, messages)) == "top-level"

    with pytest.raises(catalog.ProviderCatalogUnavailable, match="text-only"):
        client.chat(agent, [{"role": "", "content": "hello"}])
    with pytest.raises(catalog.ProviderCatalogUnavailable, match="text-only"):
        client.chat(agent, [{"role": "user", "content": 4}])


def test_non_bytez_provider_delegates_existing_mock_chat_stream_and_proxy() -> None:
    """Provider awareness leaves all existing non-Bytez transport behavior intact."""
    client = catalog.ProviderAwareModelClient()
    agent = ModelAgent("general_agent", "mock-generalist", "mock://local")
    assert client.chat(agent, [{"role": "user", "content": "hello"}])
    assert "".join(client.stream_chat(agent, [{"role": "user", "content": "hello"}]))
    assert isinstance(client.proxy_send(agent, "/responses", {"input": "hello"}), dict)


def test_scalar_helpers_bound_context_prices_and_string_metadata() -> None:
    """Scalar values, overflow, invalid iterables, and finite prices follow one policy."""
    model = catalog.normalize_models_document(
        {
            "data": [
                {
                    "id": "qwen-instruct",
                    "capabilities": 7,
                    "modalities": "TEXT",
                    "context_window": "10000000001",
                    "pricing": {"prompt": "not-a-number", "completion": "0.0000005"},
                }
            ]
        }
    )[0]
    assert model.modalities == ("text",)
    assert model.context_window is None
    assert model.input_price_usd_per_million is None
    assert model.output_price_usd_per_million == pytest.approx(0.5)
