"""Contracts for durable multi-provider discovery, bootstrap, and routing."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    get_credential,
    set_backend,
)
from contextual_orchestrator.provider_catalog import (  # noqa: E402
    DEFAULT_PROVIDER_ACCOUNTS,
    PROVIDER_CATALOG_SCHEMA_SQL,
    CatalogHttpError,
    DiscoveredModel,
    InMemoryProviderCatalogStore,
    ProviderCatalogService,
    ProviderCatalogUnavailable,
    bootstrap_provider_credentials,
    build_catalog_orchestrator,
    normalize_models_document,
)


@pytest.fixture(autouse=True)
def _isolated_credentials():
    """Keep every provider bootstrap test isolated from ambient credentials."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _models(*names: str) -> list[DiscoveredModel]:
    """Build deterministic model fixtures for one provider account."""
    return [
        DiscoveredModel(
            model_name=name,
            display_name=name,
            capabilities=("chat", "reasoning"),
            modalities=("text",),
            context_window=131_072,
            input_price_usd_per_million=1.0,
            output_price_usd_per_million=2.0,
        )
        for name in names
    ]


def test_default_accounts_cover_every_configured_secret_and_split_nvidia_accounts() -> None:
    """The built-in catalog maps all five GitHub secret names without collapsing NIM keys."""
    credential_names = [account.credential_name for account in DEFAULT_PROVIDER_ACCOUNTS]
    assert credential_names == [
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "BYTEZ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ]
    account_ids = {account.provider_account_id for account in DEFAULT_PROVIDER_ACCOUNTS}
    assert "nvidia_nim_primary" in account_ids
    assert "nvidia_nim_secondary" in account_ids
    assert len(account_ids) == 5


def test_bootstrap_registers_all_credentials_without_returning_values() -> None:
    """One-shot environment transport writes every secret into KV and reports names only."""
    environment = {
        account.credential_name: f"secret-{index}-value"
        for index, account in enumerate(DEFAULT_PROVIDER_ACCOUNTS)
    }

    summary = bootstrap_provider_credentials(environment, require_all=True)

    assert summary == {
        "registered_credentials": [account.credential_name for account in DEFAULT_PROVIDER_ACCOUNTS],
        "missing_credentials": [],
    }
    for account in DEFAULT_PROVIDER_ACCOUNTS:
        assert get_credential(account.credential_name) == environment[account.credential_name]
    serialized = json.dumps(summary)
    assert "secret-" not in serialized


def test_bootstrap_fails_closed_before_partial_write_when_required_secret_is_missing() -> None:
    """Required bootstrap validates the complete fixed inventory before mutating KV."""
    environment = {
        account.credential_name: "configured-value"
        for account in DEFAULT_PROVIDER_ACCOUNTS[:-1]
    }

    with pytest.raises(ProviderCatalogUnavailable, match="provider credential inventory is incomplete"):
        bootstrap_provider_credentials(environment, require_all=True)

    for account in DEFAULT_PROVIDER_ACCOUNTS:
        assert get_credential(account.credential_name) is None


def test_models_document_normalizes_openai_shape_and_rejects_invalid_rows() -> None:
    """OpenAI-compatible listings become bounded provider-neutral model records."""
    models = normalize_models_document(
        {
            "data": [
                {"id": "alpha/reasoner", "context_length": 200_000, "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
                {"id": "vision-model", "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}},
                {"id": ""},
                {"object": "model"},
            ]
        }
    )

    assert [model.model_name for model in models] == ["alpha/reasoner", "vision-model"]
    assert models[0].context_window == 200_000
    assert models[0].input_price_usd_per_million == pytest.approx(1.0)
    assert models[0].output_price_usd_per_million == pytest.approx(2.0)
    assert "vision" in models[1].capabilities
    assert models[1].modalities == ("image", "text")


def test_refresh_isolates_provider_failure_and_preserves_last_known_good_catalog() -> None:
    """A failed account refresh cannot erase its prior usable model set or stop peers."""
    store = InMemoryProviderCatalogStore()
    primary, secondary = DEFAULT_PROVIDER_ACCOUNTS[:2]
    store.replace_catalog(primary, _models("nim-primary-old"))
    store.replace_catalog(secondary, _models("nim-secondary-old"))

    def discover(account, _credential):
        if account.provider_account_id == primary.provider_account_id:
            raise CatalogHttpError("provider_unavailable", transient=True)
        return _models("nim-secondary-new")

    for account in (primary, secondary):
        set_backend_value = get_credential(account.credential_name)
        assert set_backend_value is None
    bootstrap_provider_credentials(
        {
            primary.credential_name: "primary-secret",
            secondary.credential_name: "secondary-secret",
        },
        require_all=False,
        accounts=(primary, secondary),
    )
    service = ProviderCatalogService(store=store, accounts=(primary, secondary), discover=discover)

    summary = service.refresh_all()

    assert summary["provider_accounts"][primary.provider_account_id]["status"] == "stale_available"
    assert summary["provider_accounts"][secondary.provider_account_id]["status"] == "refreshed"
    enabled = {(row.provider_account_id, row.model.model_name) for row in store.enabled_models()}
    assert (primary.provider_account_id, "nim-primary-old") in enabled
    assert (secondary.provider_account_id, "nim-secondary-new") in enabled
    assert (secondary.provider_account_id, "nim-secondary-old") not in enabled


def test_refresh_raises_only_when_no_fresh_or_last_known_good_candidate_exists() -> None:
    """An empty first bootstrap fails loudly instead of starting with a mock or empty pool."""
    account = DEFAULT_PROVIDER_ACCOUNTS[0]
    bootstrap_provider_credentials({account.credential_name: "secret"}, require_all=False, accounts=(account,))
    service = ProviderCatalogService(
        store=InMemoryProviderCatalogStore(),
        accounts=(account,),
        discover=lambda _account, _credential: (_ for _ in ()).throw(
            CatalogHttpError("provider_unavailable", transient=True)
        ),
    )

    with pytest.raises(ProviderCatalogUnavailable, match="no usable provider model"):
        service.refresh_all()


def test_catalog_builds_distinct_agents_and_keeps_credential_names_not_values() -> None:
    """Discovered models become valid ModelAgent rows with provider-account isolation."""
    store = InMemoryProviderCatalogStore()
    primary, secondary = DEFAULT_PROVIDER_ACCOUNTS[:2]
    store.replace_catalog(primary, _models("shared-model"))
    store.replace_catalog(secondary, _models("shared-model"))

    agents = ProviderCatalogService(store=store, accounts=(primary, secondary)).candidate_agents()

    assert len(agents) == 2
    assert len({agent.id for agent in agents}) == 2
    assert {agent.credential_key for agent in agents} == {
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
    }
    assert {agent.provider_name for agent in agents} == {"nvidia_nim"}
    assert all("secret" not in json.dumps(agent.to_config()).lower() for agent in agents)


def test_catalog_orchestrator_assigns_role_capable_models_and_retains_failover_pool() -> None:
    """The paper-grounded orchestrator receives the complete role-tagged candidate pool."""
    store = InMemoryProviderCatalogStore()
    reasoning_account = DEFAULT_PROVIDER_ACCOUNTS[0]
    coding_account = DEFAULT_PROVIDER_ACCOUNTS[3]
    store.replace_catalog(
        reasoning_account,
        [
            DiscoveredModel(
                model_name="deep-reasoner",
                display_name="Deep Reasoner",
                capabilities=("chat", "reasoning"),
                modalities=("text",),
                context_window=200_000,
            )
        ],
    )
    store.replace_catalog(
        coding_account,
        [
            DiscoveredModel(
                model_name="code-specialist",
                display_name="Code Specialist",
                capabilities=("chat", "coding"),
                modalities=("text",),
                context_window=128_000,
            )
        ],
    )

    orchestrator = build_catalog_orchestrator(store, accounts=(reasoning_account, coding_account))

    assert len(orchestrator.agents) == 2
    assert orchestrator._select_agent("plan and analyze", "thinker").model == "deep-reasoner"
    assert orchestrator._select_agent("implement this code", "worker").model == "code-specialist"
    assert len(orchestrator._failover_candidates(orchestrator.agents[0], "verify", "verifier")) == 2


def test_disabled_provider_account_is_excluded_without_deleting_catalog_history() -> None:
    """Governance can disable an account while retaining its catalog and refresh evidence."""
    store = InMemoryProviderCatalogStore()
    account = DEFAULT_PROVIDER_ACCOUNTS[0]
    store.replace_catalog(account, _models("candidate-model"))
    store.upsert_account(replace(account, enabled=False))

    assert ProviderCatalogService(store=store, accounts=(account,)).candidate_agents() == []
    assert len(store.all_models()) == 1


def test_schema_is_normalized_and_never_stores_provider_secret_values() -> None:
    """The production catalog DDL keeps credentials referenced by name in normalized tables."""
    normalized = " ".join(PROVIDER_CATALOG_SCHEMA_SQL.lower().split())
    for table_name in (
        "provider_accounts",
        "provider_models",
        "model_capabilities",
        "model_modalities",
        "catalog_refresh_runs",
    ):
        assert f"create table if not exists {table_name}" in normalized
    assert "references provider_accounts" in normalized
    assert "references provider_models" in normalized
    assert "credential_name" in normalized
    assert "secret_value" not in normalized
    assert "api_key_value" not in normalized
    assert "encrypted_value" not in normalized
