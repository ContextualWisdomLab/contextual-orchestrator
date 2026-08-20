"""Regression coverage for provider credential promotion around catalog refresh."""

from __future__ import annotations

import pytest

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    get_credential,
    register_credential,
    set_backend,
)
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    ProviderDiscoveryError,
    ProviderModelSource,
)
from contextual_orchestrator.provider_bootstrap import ProviderBootstrapError
from contextual_orchestrator.provider_catalog_bootstrap import (
    bootstrap_provider_catalog_runtime,
)
from contextual_orchestrator.provider_catalog_store import (
    InMemoryProviderCatalogStore,
)


@pytest.fixture(autouse=True)
def isolated_credential_backend():
    """Give every promotion test a fresh credential registry."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _source() -> ProviderModelSource:
    return ProviderModelSource(
        provider_name="openai",
        credential_name="OPENAI_API_KEY",
        list_url="https://api.openai.example/v1/models",
        chat_base_url="https://api.openai.example/v1",
    )


def _model(source: ProviderModelSource, model_id: str) -> DiscoveredModel:
    return DiscoveredModel(
        provider_name=source.provider_name,
        model_id=model_id,
        credential_name=source.credential_name,
        chat_base_url=source.chat_base_url,
        auth_scheme=source.auth_scheme,
        prompt_price_per_1k=1.0,
        completion_price_per_1k=2.0,
    )


def _seed_last_known_good(
    store: InMemoryProviderCatalogStore,
    source: ProviderModelSource,
) -> None:
    model = _model(source, "gpt-last-known-good")
    store.record_success(
        source,
        [model],
        eligible_model_ids={model.model_id},
        serving_tags={model.model_id: ("discovered", "chat", "worker")},
    )


def test_failed_refresh_restores_previous_credential_before_using_lkg() -> None:
    """An invalid candidate key must not replace the key paired with LKG models."""
    source = _source()
    store = InMemoryProviderCatalogStore()
    _seed_last_known_good(store, source)
    register_credential(source.credential_name, "old-working-secret")

    def failing_discovery(_sources):
        assert get_credential(source.credential_name) == "new-invalid-secret"
        return [], [ProviderDiscoveryError(source.provider_name, "unauthorized")]

    report = bootstrap_provider_catalog_runtime(
        environ={source.credential_name: "new-invalid-secret"},
        require_all_credentials=False,
        catalog_store=store,
        sources=(source,),
        discovery=failing_discovery,
        model_limit=1,
    )

    assert get_credential(source.credential_name) == "old-working-secret"
    assert report.selected_agent_ids == ("openai_gpt_last_known_good",)
    assert report.restored_credentials == (source.credential_name,)


def test_empty_refresh_restores_previous_credential_before_using_lkg() -> None:
    """An empty candidate-key catalog is failure, not credential promotion."""
    source = _source()
    store = InMemoryProviderCatalogStore()
    _seed_last_known_good(store, source)
    register_credential(source.credential_name, "old-working-secret")

    report = bootstrap_provider_catalog_runtime(
        environ={source.credential_name: "new-empty-catalog-secret"},
        require_all_credentials=False,
        catalog_store=store,
        sources=(source,),
        discovery=lambda _sources: ([], []),
        model_limit=1,
    )

    assert get_credential(source.credential_name) == "old-working-secret"
    assert report.selected_agent_ids == ("openai_gpt_last_known_good",)
    assert report.restored_credentials == (source.credential_name,)


def test_failed_first_promotion_cannot_activate_lkg_without_a_prior_credential() -> None:
    """Persisted models are unusable when the candidate key failed and no old key exists."""
    source = _source()
    store = InMemoryProviderCatalogStore()
    _seed_last_known_good(store, source)

    with pytest.raises(
        ProviderBootstrapError,
        match="no persisted chat-compatible model with a usable credential",
    ):
        bootstrap_provider_catalog_runtime(
            environ={source.credential_name: "first-invalid-secret"},
            require_all_credentials=False,
            catalog_store=store,
            sources=(source,),
            discovery=lambda _sources: (
                [],
                [ProviderDiscoveryError(source.provider_name, "unauthorized")],
            ),
            model_limit=1,
        )

    assert get_credential(source.credential_name) is None


def test_report_excludes_first_promotion_credential_removed_by_rollback() -> None:
    """Durable-registration evidence cannot claim a deleted first candidate key."""
    openai = _source()
    openrouter = ProviderModelSource(
        provider_name="openrouter",
        credential_name="OPENROUTER_API_KEY",
        list_url="https://openrouter.example/v1/models",
        chat_base_url="https://openrouter.example/v1",
    )
    live = _model(openrouter, "router-live")

    report = bootstrap_provider_catalog_runtime(
        environ={
            openai.credential_name: "first-invalid-secret",
            openrouter.credential_name: "working-router-secret",
        },
        require_all_credentials=False,
        catalog_store=InMemoryProviderCatalogStore(),
        sources=(openai, openrouter),
        discovery=lambda _sources: (
            [live],
            [ProviderDiscoveryError(openai.provider_name, "temporary discovery failure")],
        ),
        model_limit=1,
    )

    assert report.restored_credentials == (openai.credential_name,)
    assert report.registered_credentials == (openrouter.credential_name,)
    assert get_credential(openai.credential_name) is None
    assert get_credential(openrouter.credential_name) == "working-router-secret"


def test_successful_refresh_promotes_the_candidate_credential() -> None:
    """A validated non-empty catalog commits the new provider credential."""
    source = _source()
    store = InMemoryProviderCatalogStore()
    register_credential(source.credential_name, "old-working-secret")
    live = _model(source, "gpt-new-live")

    report = bootstrap_provider_catalog_runtime(
        environ={source.credential_name: "new-working-secret"},
        require_all_credentials=False,
        catalog_store=store,
        sources=(source,),
        discovery=lambda _sources: ([live], []),
        model_limit=1,
    )

    assert get_credential(source.credential_name) == "new-working-secret"
    assert report.selected_agent_ids == ("openai_gpt_new_live",)
    assert report.restored_credentials == ()
