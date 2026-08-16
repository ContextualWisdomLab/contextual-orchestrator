"""Behavioral contracts for provider discovery, persistence, and routing."""

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
from contextual_orchestrator.orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.provider_catalog import (  # noqa: E402
    DEFAULT_PROVIDER_ACCOUNTS,
    CatalogHttpError,
    DiscoveredModel,
    InMemoryProviderCatalogStore,
    ProviderAwareModelClient,
    ProviderCatalogService,
    ProviderCatalogUnavailable,
    bootstrap_provider_credentials,
    build_catalog_orchestrator,
    normalize_models_document,
    _bytez_model_path,
)
from contextual_orchestrator.provider_catalog_postgres import (  # noqa: E402
    PROVIDER_CATALOG_SCHEMA_SQL,
)


@pytest.fixture(autouse=True)
def _isolated_credentials():
    """Use a fresh in-memory credential registry for every contract test."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _chat_models(*names: str) -> list[DiscoveredModel]:
    """Build deterministic chat-capable model fixtures."""
    return [
        DiscoveredModel(
            model_name=name,
            display_name=name,
            capabilities=("chat", "reasoning"),
            modalities=("text",),
            context_window=200_000,
            input_price_usd_per_million=0.5,
            output_price_usd_per_million=1.0,
        )
        for name in names
    ]


def test_fixed_inventory_covers_five_secrets_and_independent_nvidia_accounts() -> None:
    """Every configured secret has one account and the two NIM quotas stay isolated."""
    assert [row.credential_name for row in DEFAULT_PROVIDER_ACCOUNTS] == [
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "BYTEZ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ]
    assert {row.provider_account_id for row in DEFAULT_PROVIDER_ACCOUNTS} == {
        "nvidia_nim_primary",
        "nvidia_nim_secondary",
        "bytez_primary",
        "openrouter_primary",
        "openai_primary",
    }
    assert DEFAULT_PROVIDER_ACCOUNTS[0].models_url == "https://integrate.api.nvidia.com/v1/models"
    assert DEFAULT_PROVIDER_ACCOUNTS[2].models_url == "https://api.bytez.com/models/v2"


def test_required_bootstrap_registers_complete_generation_without_echoing_values() -> None:
    """Trusted bootstrap writes every credential and returns names only."""
    environment = {
        account.credential_name: f"secret-{index}-value"
        for index, account in enumerate(DEFAULT_PROVIDER_ACCOUNTS)
    }

    summary = bootstrap_provider_credentials(environment, require_all=True)

    assert summary == {
        "registered_credentials": [row.credential_name for row in DEFAULT_PROVIDER_ACCOUNTS],
        "missing_credentials": [],
    }
    for account in DEFAULT_PROVIDER_ACCOUNTS:
        assert get_credential(account.credential_name) == environment[account.credential_name]
    assert "secret-" not in json.dumps(summary)


def test_required_bootstrap_validates_inventory_before_any_write() -> None:
    """A missing production secret prevents a partially rotated registry state."""
    environment = {
        row.credential_name: "configured-value"
        for row in DEFAULT_PROVIDER_ACCOUNTS[:-1]
    }

    with pytest.raises(ProviderCatalogUnavailable, match="inventory is incomplete"):
        bootstrap_provider_credentials(environment, require_all=True)

    assert all(get_credential(row.credential_name) is None for row in DEFAULT_PROVIDER_ACCOUNTS)


def test_optional_bootstrap_registers_present_values_and_reports_missing_names() -> None:
    """Local bootstrap can seed a subset while keeping omissions explicit."""
    first, second = DEFAULT_PROVIDER_ACCOUNTS[:2]

    summary = bootstrap_provider_credentials(
        {first.credential_name: "present"},
        require_all=False,
        accounts=(first, second),
    )

    assert summary == {
        "registered_credentials": [first.credential_name],
        "missing_credentials": [second.credential_name],
    }
    assert get_credential(first.credential_name) == "present"
    assert get_credential(second.credential_name) is None


def test_normalizer_preserves_known_metadata_and_conservative_capabilities() -> None:
    """Common catalog shapes retain evidence without classifying every model as chat."""
    models = normalize_models_document(
        {
            "data": [
                {
                    "id": "vendor/deepseek-r1",
                    "name": "Deep Reasoner",
                    "context_length": 200_000,
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                },
                {"id": "text-embedding-3-large"},
                {"id": "gpt-image-1"},
                {"id": "unknown-scientific-model"},
                {
                    "id": "declared-worker",
                    "capabilities": ["chat", "CODING"],
                    "modalities": ["text", "image"],
                },
            ]
        }
    )
    by_name = {model.model_name: model for model in models}

    reasoner = by_name["vendor/deepseek-r1"]
    assert reasoner.capabilities == ("chat", "reasoning")
    assert reasoner.context_window == 200_000
    assert reasoner.input_price_usd_per_million == pytest.approx(1.0)
    assert reasoner.output_price_usd_per_million == pytest.approx(2.0)
    assert by_name["text-embedding-3-large"].capabilities == ("embeddings",)
    assert by_name["gpt-image-1"].capabilities == ("image_generation",)
    assert by_name["unknown-scientific-model"].capabilities == ("unknown",)
    assert by_name["declared-worker"].capabilities == ("chat", "coding", "vision")
    assert by_name["declared-worker"].modalities == ("image", "text")


def test_normalizer_accepts_mapping_and_string_rows_but_rejects_bad_metadata() -> None:
    """Alternate listing shapes remain deterministic and unsafe numeric values stay null."""
    models = normalize_models_document(
        {
            "models": {
                "one": "meta-llama/llama-3.3-instruct",
                "two": {
                    "name": "invalid-metadata",
                    "context_window": object(),
                    "pricing": {"prompt": "nan", "completion": "-1"},
                },
                "three": {"id": ""},
                "four": 7,
                "five": {"id": "x" * 513},
            }
        }
    )

    assert [row.model_name for row in models] == [
        "invalid-metadata",
        "meta-llama/llama-3.3-instruct",
    ]
    invalid = models[0]
    assert invalid.capabilities == ("unknown",)
    assert invalid.context_window is None
    assert invalid.input_price_usd_per_million is None
    assert invalid.output_price_usd_per_million is None
    assert normalize_models_document({"data": "not-a-list"}) == []


def test_refresh_isolates_failure_and_preserves_last_known_good_models() -> None:
    """One account can stay stale while a peer atomically replaces its catalog."""
    store = InMemoryProviderCatalogStore()
    primary, secondary = DEFAULT_PROVIDER_ACCOUNTS[:2]
    store.replace_catalog(primary, _chat_models("old-primary"))
    store.replace_catalog(secondary, _chat_models("old-secondary"))
    bootstrap_provider_credentials(
        {
            primary.credential_name: "primary-secret",
            secondary.credential_name: "secondary-secret",
        },
        require_all=False,
        accounts=(primary, secondary),
    )

    def discover(account: object, _credential: str) -> list[DiscoveredModel]:
        if getattr(account, "provider_account_id") == primary.provider_account_id:
            raise CatalogHttpError("catalog_http_503", transient=True)
        return _chat_models("new-secondary")

    summary = ProviderCatalogService(
        store=store,
        accounts=(primary, secondary),
        discover=discover,
    ).refresh_all()

    assert summary["provider_accounts"][primary.provider_account_id]["status"] == "stale_available"
    assert summary["provider_accounts"][secondary.provider_account_id]["status"] == "refreshed"
    enabled = {(row.provider_account_id, row.model.model_name) for row in store.enabled_models()}
    assert (primary.provider_account_id, "old-primary") in enabled
    assert (secondary.provider_account_id, "new-secondary") in enabled
    assert (secondary.provider_account_id, "old-secondary") not in enabled


def test_refresh_classifies_disabled_missing_and_unexpected_adapter_failures() -> None:
    """Configuration and adapter failures remain provider-local and secret-free."""
    missing = DEFAULT_PROVIDER_ACCOUNTS[0]
    disabled = replace(DEFAULT_PROVIDER_ACCOUNTS[1], enabled=False)
    broken = DEFAULT_PROVIDER_ACCOUNTS[2]
    bootstrap_provider_credentials(
        {broken.credential_name: "configured"},
        require_all=False,
        accounts=(broken,),
    )
    service = ProviderCatalogService(
        store=InMemoryProviderCatalogStore(),
        accounts=(missing, disabled, broken),
        discover=lambda _account, _credential: (_ for _ in ()).throw(
            RuntimeError("provider-body-private-detail")
        ),
    )

    with pytest.raises(ProviderCatalogUnavailable):
        service.refresh_all()

    rows = service.last_refresh_summary["provider_accounts"]
    assert rows[missing.provider_account_id]["error_code"] == "credential_not_registered"
    assert rows[disabled.provider_account_id]["status"] == "disabled"
    assert rows[broken.provider_account_id]["error_code"] == "catalog_adapter_failure"
    assert "provider-body-private-detail" not in json.dumps(rows)


def test_refresh_rejects_empty_adapter_result_without_erasing_prior_catalog() -> None:
    """An empty adapter result is a failed refresh rather than a destructive success."""
    account = DEFAULT_PROVIDER_ACCOUNTS[4]
    store = InMemoryProviderCatalogStore()
    store.replace_catalog(account, _chat_models("prior-chat"))
    bootstrap_provider_credentials(
        {account.credential_name: "credential"},
        require_all=False,
        accounts=(account,),
    )

    summary = ProviderCatalogService(
        store=store,
        accounts=(account,),
        discover=lambda _account, _credential: [],
    ).refresh_all()

    assert summary["provider_accounts"][account.provider_account_id] == {
        "status": "stale_available",
        "model_count": 0,
        "error_code": "catalog_contains_no_models",
    }
    assert store.enabled_models()[0].model.model_name == "prior-chat"


def test_refresh_fails_closed_when_only_non_chat_inventory_exists() -> None:
    """Embeddings and unknown models are cataloged but cannot start a chat gateway."""
    account = DEFAULT_PROVIDER_ACCOUNTS[4]
    bootstrap_provider_credentials(
        {account.credential_name: "credential"},
        require_all=False,
        accounts=(account,),
    )
    service = ProviderCatalogService(
        store=InMemoryProviderCatalogStore(),
        accounts=(account,),
        discover=lambda _account, _credential: [
            DiscoveredModel("text-embedding", "Embedding", ("embeddings",)),
            DiscoveredModel("unknown-model", "Unknown", ("unknown",)),
        ],
    )

    with pytest.raises(ProviderCatalogUnavailable, match="chat-capable"):
        service.refresh_all()

    assert len(service.store.all_models()) == 2


def test_candidate_agents_filter_non_chat_models_and_keep_credentials_distinct() -> None:
    """Only serving-capable rows become agents and keys remain registry names."""
    store = InMemoryProviderCatalogStore()
    primary, secondary = DEFAULT_PROVIDER_ACCOUNTS[:2]
    store.replace_catalog(
        primary,
        [*_chat_models("shared-model"), DiscoveredModel("embed-only", "Embed", ("embeddings",))],
    )
    store.replace_catalog(secondary, _chat_models("shared-model"))

    agents = ProviderCatalogService(store=store, accounts=(primary, secondary)).candidate_agents()

    assert len(agents) == 2
    assert len({agent.id for agent in agents}) == 2
    assert {agent.credential_key for agent in agents} == {
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
    }
    assert all("secret" not in json.dumps(agent.to_config()).lower() for agent in agents)


def test_catalog_orchestrator_uses_role_tags_and_cross_provider_failover() -> None:
    """The existing paper-grounded engine receives the complete eligible pool."""
    store = InMemoryProviderCatalogStore()
    reasoning = DEFAULT_PROVIDER_ACCOUNTS[0]
    coding = DEFAULT_PROVIDER_ACCOUNTS[3]
    store.replace_catalog(
        reasoning,
        [DiscoveredModel("deepseek-r1", "Reasoner", ("chat", "reasoning"), ("text",), 200_000)],
    )
    store.replace_catalog(
        coding,
        [DiscoveredModel("codestral-coder", "Coder", ("chat", "coding"), ("text",), 128_000)],
    )

    orchestrator = build_catalog_orchestrator(store, accounts=(reasoning, coding))

    assert orchestrator._select_agent("plan and analyze", "thinker").model == "deepseek-r1"
    assert orchestrator._select_agent("implement code", "worker").model == "codestral-coder"
    assert len(orchestrator._failover_candidates(orchestrator.agents[0], "verify", "verifier")) == 2


def test_disabled_account_is_not_served_but_history_remains() -> None:
    """Governance disablement removes candidates without deleting model evidence."""
    store = InMemoryProviderCatalogStore()
    account = DEFAULT_PROVIDER_ACCOUNTS[0]
    store.replace_catalog(account, _chat_models("candidate-model"))
    disabled = replace(account, enabled=False)
    store.upsert_account(disabled)

    assert ProviderCatalogService(store=store, accounts=(disabled,)).candidate_agents() == []
    assert len(store.all_models()) == 1


def test_bytez_native_chat_serializes_messages_and_normalizes_output() -> None:
    """Bytez uses a native Key/input seam rather than an invented Bearer chat call."""
    account = DEFAULT_PROVIDER_ACCOUNTS[2]
    bootstrap_provider_credentials(
        {account.credential_name: "bytez-secret"},
        require_all=False,
        accounts=(account,),
    )
    captured: list[tuple[ModelAgent, str, str]] = []

    def bytez_request(agent: ModelAgent, prompt: str, credential: str) -> dict[str, object]:
        captured.append((agent, prompt, credential))
        return {"output": {"generated_text": "native-answer"}}

    client = ProviderAwareModelClient(bytez_request=bytez_request)
    agent = ModelAgent(
        "bytez_worker",
        "owner/model",
        account.base_url,
        credential_key=account.credential_name,
        provider_name="bytez",
    )

    answer = client.chat(
        agent,
        [
            {"role": "system", "content": "Be exact."},
            {"role": "user", "content": "Answer."},
        ],
    )

    assert answer == "native-answer"
    assert captured[0][1] == "system: Be exact.\nuser: Answer.\nassistant:"
    assert captured[0][2] == "bytez-secret"
    assert client.take_usage() is None


def test_bytez_retries_transient_native_failures_and_stops_on_permanent_error() -> None:
    """Native Bytez calls use bounded retry and stable error codes."""
    account = DEFAULT_PROVIDER_ACCOUNTS[2]
    bootstrap_provider_credentials(
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
    calls: list[int] = []

    def transient_then_success(_agent: ModelAgent, _prompt: str, _credential: str) -> dict[str, str]:
        calls.append(1)
        if len(calls) < 3:
            raise CatalogHttpError("catalog_http_503", transient=True)
        return {"output": "recovered"}

    client = ProviderAwareModelClient(bytez_request=transient_then_success, max_retries=2)
    sleeps: list[float] = []
    client._sleep = sleeps.append
    client._backoff_delay = lambda attempt: float(attempt + 1)  # type: ignore[method-assign]
    assert client.chat(agent, [{"role": "user", "content": "hello"}]) == "recovered"
    assert sleeps == [1.0, 2.0]

    permanent_calls: list[int] = []

    def permanent(_agent: ModelAgent, _prompt: str, _credential: str) -> dict[str, str]:
        permanent_calls.append(1)
        raise CatalogHttpError("catalog_authentication_failed")

    permanent_client = ProviderAwareModelClient(bytez_request=permanent, max_retries=3)
    with pytest.raises(ProviderCatalogUnavailable, match="catalog_authentication_failed"):
        permanent_client.chat(agent, [{"role": "user", "content": "hello"}])
    assert permanent_calls == [1]


def test_bytez_failures_do_not_guess_credentials_messages_outputs_or_passthrough() -> None:
    """Native Bytez boundaries fail closed on every ambiguous input or output."""
    account = DEFAULT_PROVIDER_ACCOUNTS[2]
    agent = ModelAgent(
        "bytez_worker",
        "owner/model",
        account.base_url,
        credential_key=account.credential_name,
        provider_name="bytez",
    )
    client = ProviderAwareModelClient(
        bytez_request=lambda _agent, _prompt, _credential: {"output": []}
    )

    with pytest.raises(ProviderCatalogUnavailable, match="credential is not registered"):
        client.chat(agent, [{"role": "user", "content": "hello"}])

    bootstrap_provider_credentials(
        {account.credential_name: "secret"},
        require_all=False,
        accounts=(account,),
    )
    with pytest.raises(ProviderCatalogUnavailable, match="text-only"):
        client.chat(agent, [{"role": "user", "content": ["not", "text"]}])  # type: ignore[list-item]
    with pytest.raises(ProviderCatalogUnavailable, match="at least one"):
        client.chat(agent, [])
    with pytest.raises(ProviderCatalogUnavailable, match="response shape"):
        client.chat(agent, [{"role": "user", "content": "hello"}])
    with pytest.raises(ProviderCatalogUnavailable, match="does not support passthrough"):
        client.proxy_send(agent, "/responses", {})


def test_bytez_model_path_preserves_namespace_and_blocks_traversal() -> None:
    """Native model ids preserve slash namespaces without permitting path escape."""
    assert _bytez_model_path("owner/model") == "owner/model"
    assert _bytez_model_path("owner name/model+tag") == "owner%20name/model%2Btag"
    for value in ("", "/model", "owner/", "owner/../model", "./model"):
        with pytest.raises(ProviderCatalogUnavailable, match="invalid path segment"):
            _bytez_model_path(value)


def test_schema_is_normalized_and_contains_no_provider_secret_column() -> None:
    """Catalog metadata references names and separates multivalued facts."""
    normalized = " ".join(PROVIDER_CATALOG_SCHEMA_SQL.lower().split())
    for table in (
        "provider_accounts",
        "provider_models",
        "model_capabilities",
        "model_modalities",
        "catalog_refresh_runs",
    ):
        assert f"create table if not exists {table}" in normalized
    assert "references provider_accounts" in normalized
    assert "references provider_models" in normalized
    assert "credential_name" in normalized
    assert "secret_value" not in normalized
    assert "encrypted_value" not in normalized
