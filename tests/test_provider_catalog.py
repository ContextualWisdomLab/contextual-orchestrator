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
    ProviderAwareModelClient,
    ProviderCatalogHttpClient,
    ProviderCatalogService,
    ProviderCatalogUnavailable,
    bootstrap_provider_credentials,
    build_catalog_orchestrator,
    normalize_models_document,
)
from contextual_orchestrator.orchestrator import ModelAgent  # noqa: E402


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
    assert account_ids == {
        "nvidia_nim_primary",
        "nvidia_nim_secondary",
        "bytez_primary",
        "openrouter_primary",
        "openai_primary",
    }


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
    assert "secret-" not in json.dumps(summary)


def test_bootstrap_fails_closed_before_partial_write_when_required_secret_is_missing() -> None:
    """Required bootstrap validates the complete fixed inventory before mutating KV."""
    environment = {
        account.credential_name: "configured-value"
        for account in DEFAULT_PROVIDER_ACCOUNTS[:-1]
    }

    with pytest.raises(ProviderCatalogUnavailable, match="inventory is incomplete"):
        bootstrap_provider_credentials(environment, require_all=True)

    assert all(get_credential(account.credential_name) is None for account in DEFAULT_PROVIDER_ACCOUNTS)


def test_optional_bootstrap_registers_present_credentials_and_reports_missing_names() -> None:
    """Non-production bootstrap may seed a subset while keeping missing names explicit."""
    first, second = DEFAULT_PROVIDER_ACCOUNTS[:2]
    summary = bootstrap_provider_credentials(
        {first.credential_name: "primary-value"},
        require_all=False,
        accounts=(first, second),
    )
    assert summary == {
        "registered_credentials": [first.credential_name],
        "missing_credentials": [second.credential_name],
    }


def test_models_document_normalizes_openai_shape_and_rejects_invalid_rows() -> None:
    """OpenAI-compatible listings become bounded provider-neutral model records."""
    models = normalize_models_document(
        {
            "data": [
                {
                    "id": "alpha/reasoner",
                    "context_length": 200_000,
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                },
                {
                    "id": "vision-model",
                    "architecture": {
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                    },
                },
                {"id": ""},
                {"object": "model"},
                42,
            ]
        }
    )

    assert [model.model_name for model in models] == ["alpha/reasoner", "vision-model"]
    assert models[0].context_window == 200_000
    assert models[0].input_price_usd_per_million == pytest.approx(1.0)
    assert models[0].output_price_usd_per_million == pytest.approx(2.0)
    assert "reasoning" in models[0].capabilities
    assert "vision" in models[1].capabilities
    assert models[1].modalities == ("image", "text")


def test_models_document_accepts_models_mapping_and_string_rows() -> None:
    """Provider-specific mapping and string inventories normalize without adapter branching."""
    models = normalize_models_document({"models": {"first": "plain-model", "second": {"name": "embed-model"}}})
    assert [model.model_name for model in models] == ["embed-model", "plain-model"]
    assert models[0].capabilities == ("embeddings",)
    assert models[1].capabilities == ("chat",)


def test_models_document_rejects_malformed_root_and_unsafe_numeric_metadata() -> None:
    """Malformed roots and non-finite/negative metadata never enter routing evidence."""
    assert normalize_models_document({"data": "not-a-list"}) == []
    model = normalize_models_document(
        {
            "data": [
                {
                    "id": "safe-model",
                    "context_length": -1,
                    "pricing": {"prompt": "nan", "completion": "-1"},
                }
            ]
        }
    )[0]
    assert model.context_window is None
    assert model.input_price_usd_per_million is None
    assert model.output_price_usd_per_million is None


def test_http_client_retries_transient_failure_with_bounded_backoff() -> None:
    """Transient catalog errors retry, while the successful document is normalized once."""
    sleeps: list[float] = []
    client = ProviderCatalogHttpClient(
        max_attempts=2,
        sleep=sleeps.append,
        random_uniform=lambda _low, high: high,
    )
    calls: list[int] = []

    def fake_request(_account, _credential):
        calls.append(1)
        if len(calls) == 1:
            raise CatalogHttpError("catalog_http_503", transient=True)
        return {"data": [{"id": "recovered-model"}]}

    client._request_json = fake_request  # type: ignore[method-assign]
    models = client.discover(DEFAULT_PROVIDER_ACCOUNTS[0], "credential")
    assert [model.model_name for model in models] == ["recovered-model"]
    assert len(calls) == 2
    assert sleeps == [0.5]


def test_http_client_does_not_retry_permanent_or_empty_catalog() -> None:
    """Authentication and structurally empty catalogs fail fast with stable codes."""
    client = ProviderCatalogHttpClient(max_attempts=3, sleep=lambda _delay: None)
    client._request_json = lambda _account, _credential: (_ for _ in ()).throw(  # type: ignore[method-assign]
        CatalogHttpError("catalog_authentication_failed")
    )
    with pytest.raises(CatalogHttpError, match="catalog_authentication_failed"):
        client.discover(DEFAULT_PROVIDER_ACCOUNTS[0], "credential")

    client._request_json = lambda _account, _credential: {"data": []}  # type: ignore[method-assign]
    with pytest.raises(CatalogHttpError, match="catalog_contains_no_models"):
        client.discover(DEFAULT_PROVIDER_ACCOUNTS[0], "credential")


def test_refresh_isolates_provider_failure_and_preserves_last_known_good_catalog() -> None:
    """A failed account refresh cannot erase its prior usable model set or stop peers."""
    store = InMemoryProviderCatalogStore()
    primary, secondary = DEFAULT_PROVIDER_ACCOUNTS[:2]
    store.replace_catalog(primary, _models("nim-primary-old"))
    store.replace_catalog(secondary, _models("nim-secondary-old"))
    bootstrap_provider_credentials(
        {
            primary.credential_name: "primary-secret",
            secondary.credential_name: "secondary-secret",
        },
        require_all=False,
        accounts=(primary, secondary),
    )

    def discover(account, _credential):
        if account.provider_account_id == primary.provider_account_id:
            raise CatalogHttpError("provider_unavailable", transient=True)
        return _models("nim-secondary-new")

    service = ProviderCatalogService(store=store, accounts=(primary, secondary), discover=discover)
    summary = service.refresh_all()

    assert summary["provider_accounts"][primary.provider_account_id]["status"] == "stale_available"
    assert summary["provider_accounts"][secondary.provider_account_id]["status"] == "refreshed"
    enabled = {(row.provider_account_id, row.model.model_name) for row in store.enabled_models()}
    assert (primary.provider_account_id, "nim-primary-old") in enabled
    assert (secondary.provider_account_id, "nim-secondary-new") in enabled
    assert (secondary.provider_account_id, "nim-secondary-old") not in enabled


def test_refresh_classifies_missing_credentials_disabled_accounts_and_adapter_failures() -> None:
    """Account-local configuration and unexpected adapter exceptions remain explicit."""
    first = DEFAULT_PROVIDER_ACCOUNTS[0]
    disabled = replace(DEFAULT_PROVIDER_ACCOUNTS[1], enabled=False)
    third = DEFAULT_PROVIDER_ACCOUNTS[2]
    bootstrap_provider_credentials({third.credential_name: "configured"}, require_all=False, accounts=(third,))
    service = ProviderCatalogService(
        store=InMemoryProviderCatalogStore(),
        accounts=(first, disabled, third),
        discover=lambda _account, _credential: (_ for _ in ()).throw(RuntimeError("private detail")),
    )
    with pytest.raises(ProviderCatalogUnavailable):
        service.refresh_all()
    rows = service.last_refresh_summary["provider_accounts"]
    assert rows[first.provider_account_id]["error_code"] == "credential_not_registered"
    assert rows[disabled.provider_account_id]["status"] == "disabled"
    assert rows[third.provider_account_id]["error_code"] == "catalog_adapter_failure"
    assert "private detail" not in json.dumps(rows)


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


def test_catalog_orchestrator_uses_role_tags_and_retains_cross_provider_failover() -> None:
    """The paper-grounded orchestrator receives role-capable candidates from distinct providers."""
    store = InMemoryProviderCatalogStore()
    reasoning_account = DEFAULT_PROVIDER_ACCOUNTS[0]
    coding_account = DEFAULT_PROVIDER_ACCOUNTS[3]
    store.replace_catalog(
        reasoning_account,
        [DiscoveredModel("deep-reasoner", "Deep Reasoner", ("chat", "reasoning"), ("text",), 200_000)],
    )
    store.replace_catalog(
        coding_account,
        [DiscoveredModel("code-specialist", "Code Specialist", ("chat", "coding"), ("text",), 128_000)],
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
    disabled = replace(account, enabled=False)
    store.upsert_account(disabled)

    assert ProviderCatalogService(store=store, accounts=(disabled,)).candidate_agents() == []
    assert len(store.all_models()) == 1


def test_bytez_client_uses_native_key_transport_and_normalizes_output() -> None:
    """Bytez candidates use their native contract instead of a fabricated OpenAI bearer call."""
    captured: list[tuple[ModelAgent, list[dict[str, str]], str]] = []

    def bytez_request(agent, messages, credential):
        captured.append((agent, messages, credential))
        return {"output": {"content": "bytez-answer"}}

    client = ProviderAwareModelClient(bytez_request=bytez_request)
    agent = ModelAgent(
        "bytez_worker",
        "owner/model",
        "https://api.bytez.com",
        credential_key="BYTEZ_API_KEY",
        provider_name="bytez",
    )
    bootstrap_provider_credentials({"BYTEZ_API_KEY": "bytez-secret"}, require_all=False, accounts=(DEFAULT_PROVIDER_ACCOUNTS[2],))

    answer = client.chat(agent, [{"role": "user", "content": "hello"}])

    assert answer == "bytez-answer"
    assert captured[0][2] == "bytez-secret"
    assert client.take_usage() is None


def test_bytez_client_fails_closed_on_missing_credential_or_unsupported_output() -> None:
    """Native transport never sends an empty key or accepts an ambiguous provider result."""
    agent = ModelAgent(
        "bytez_worker",
        "owner/model",
        "https://api.bytez.com",
        credential_key="BYTEZ_API_KEY",
        provider_name="bytez",
    )
    client = ProviderAwareModelClient(bytez_request=lambda _agent, _messages, _credential: {"output": []})
    with pytest.raises(ProviderCatalogUnavailable, match="credential is not registered"):
        client.chat(agent, [{"role": "user", "content": "hello"}])

    bootstrap_provider_credentials({"BYTEZ_API_KEY": "secret"}, require_all=False, accounts=(DEFAULT_PROVIDER_ACCOUNTS[2],))
    with pytest.raises(ProviderCatalogUnavailable, match="response shape is unsupported"):
        client.chat(agent, [{"role": "user", "content": "hello"}])

    empty_mapping_client = ProviderAwareModelClient(
        bytez_request=lambda _agent, _messages, _credential: {"output": {}}
    )
    with pytest.raises(ProviderCatalogUnavailable, match="response shape is unsupported"):
        empty_mapping_client.chat(agent, [{"role": "user", "content": "hello"}])


def test_non_bytez_client_delegates_to_existing_model_client_mock_path() -> None:
    """Provider awareness leaves the existing mock/OpenAI-compatible behavior unchanged."""
    client = ProviderAwareModelClient()
    agent = ModelAgent("general_agent", "mock-generalist", "mock://local")
    assert client.chat(agent, [{"role": "user", "content": "hello"}])


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
