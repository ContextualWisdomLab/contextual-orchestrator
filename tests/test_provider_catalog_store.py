"""Provider catalog persistence and last-known-good contracts."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    ProviderModelSource,
    _currency_is_comparable,
)
from contextual_orchestrator.provider_catalog_store import (
    InMemoryProviderCatalogStore,
    PostgresProviderCatalogStore,
    PROVIDER_CATALOG_SCHEMA_SQL,
    ProviderCatalogError,
    normalize_discovered_model,
    provider_account_id,
)


def _source(
    provider: str = "nvidia_nim",
    credential: str = "NVIDIA_NIM_API_KEY",
) -> ProviderModelSource:
    return ProviderModelSource(
        provider_name=provider,
        credential_name=credential,
        list_url=f"https://{provider}.example/v1/models",
        chat_base_url=f"https://{provider}.example/v1",
    )


def _model(
    source: ProviderModelSource,
    model_id: str,
    prompt_price: object = 1.0,
) -> DiscoveredModel:
    return DiscoveredModel(
        provider_name=source.provider_name,
        model_id=model_id,
        credential_name=source.credential_name,
        chat_base_url=source.chat_base_url,
        auth_scheme=source.auth_scheme,
        prompt_price_per_1k=prompt_price,
        completion_price_per_1k=prompt_price,
        currency_code="usd",
    )


def test_schema_is_normalized_and_contains_no_secret_value_column() -> None:
    """Catalog DDL keeps accounts, models, tags, and refresh evidence separate."""
    for table in (
        "provider_account",
        "provider_model",
        "model_serving_tag",
        "catalog_refresh_run",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in PROVIDER_CATALOG_SCHEMA_SQL
    lowered = PROVIDER_CATALOG_SCHEMA_SQL.casefold()
    assert "api_key" not in lowered
    assert "secret_value" not in lowered
    assert "encrypted_value" not in lowered
    model_table = lowered.split(
        "create table if not exists provider_model (", 1
    )[1].split(");", 1)[0]
    assert "chat_base_url" not in model_table
    assert "auth_scheme" not in model_table


def test_primary_and_secondary_nim_accounts_have_distinct_ids() -> None:
    """Two NIM credentials remain independent quota and failure domains."""
    primary = _source(credential="NVIDIA_NIM_API_KEY")
    secondary = _source(
        provider="nvidia_nim_sub",
        credential="NVIDIA_NIM_API_KEY_SUB",
    )
    assert provider_account_id(primary) != provider_account_id(secondary)


def test_model_normalization_rejects_cross_account_rows_and_bad_prices() -> None:
    """Catalog normalization is account-bound and never stores non-finite prices."""
    source = _source()
    wrong = _model(
        _source(provider="openai", credential="OPENAI_API_KEY"),
        "gpt-test",
    )
    with pytest.raises(ProviderCatalogError, match="different account"):
        normalize_discovered_model(source, wrong)

    normalized = normalize_discovered_model(
        source,
        _model(source, "  model-a  ", float("nan")),
    )
    assert normalized.model_id == "model-a"
    assert normalized.prompt_price_per_1k is None
    assert normalized.completion_price_per_1k is None
    assert normalized.currency_code == "USD"


def test_underflowing_positive_price_is_rejected_not_treated_as_free() -> None:
    """A nonzero price that underflows to 0.0 in float must stay unknown."""
    source = _source()
    normalized = normalize_discovered_model(
        source, _model(source, "underflow-model", "1e-10000")
    )
    assert normalized.prompt_price_per_1k is None
    assert normalized.completion_price_per_1k is None


def test_overflowing_price_is_rejected_not_treated_as_infinite() -> None:
    """A Decimal-finite price whose float() conversion overflows to inf must stay unknown."""
    source = _source()
    normalized = normalize_discovered_model(
        source, _model(source, "overflow-model", "1e10000")
    )
    assert normalized.prompt_price_per_1k is None
    assert normalized.completion_price_per_1k is None


def test_unrecognized_currency_is_preserved_as_unknown_not_coerced_to_usd() -> None:
    """A priced model with an unverifiable currency must not rank as comparable USD."""
    source = _source()
    garbage_currency = replace(
        _model(source, "mystery-currency-model"), currency_code="not a currency"
    )
    normalized = normalize_discovered_model(source, garbage_currency)
    assert normalized.prompt_price_per_1k == 1.0
    assert normalized.currency_code != "USD"
    assert not _currency_is_comparable(normalized.currency_code, "USD")


def test_success_replaces_current_rows_and_failure_keeps_last_known_good() -> None:
    """A failed refresh cannot erase the last successful serving model set."""
    store = InMemoryProviderCatalogStore()
    source = _source()
    store.record_success(
        source,
        [_model(source, "model-a"), _model(source, "model-b")],
        eligible_model_ids={"model-a"},
        serving_tags={"model-a": ("discovered", "chat", "chat")},
    )
    assert [model.model_id for model in store.serving_models(source)] == [
        "model-a"
    ]
    assert store.serving_tags(source, "model-a") == ("discovered", "chat")

    store.record_failure(source, error_code="provider_timeout: secret-token")
    assert [model.model_id for model in store.serving_models(source)] == [
        "model-a"
    ]
    assert store.refresh_evidence()[-1].error_code == "unknown_error"

    store.record_success(
        source,
        [_model(source, "model-c")],
        eligible_model_ids={"model-c"},
        serving_tags={"model-c": ("discovered", "chat")},
    )
    assert [model.model_id for model in store.serving_models(source)] == [
        "model-c"
    ]
    assert [item.refresh_status for item in store.refresh_evidence()] == [
        "succeeded",
        "failed",
        "succeeded",
    ]


def test_last_known_good_restores_free_and_modality_evidence() -> None:
    """A catalog round trip cannot silently turn a free multimodal model unknown."""
    source = _source(provider="opencode_zen", credential="OPENCODE_ZEN_API_KEY")
    model = replace(
        _model(source, "free-multimodal-model", 0),
        capabilities=("chat", "text"),
        input_modalities=("text", "image"),
        output_modalities=("text",),
        currency_code="USD",
        is_free=True,
    )
    store = InMemoryProviderCatalogStore()
    store.record_success(
        source,
        [model],
        eligible_model_ids={model.model_id},
        serving_tags={
            model.model_id: (
                "discovered",
                "chat",
                "text",
                "capability:chat",
                "capability:text",
                "cost:free",
                "input:text",
                "input:image",
                "output:text",
            )
        },
    )

    assert store.serving_models(source) == [model]


class _FakeCursor:
    """Minimal DB-API cursor recording parameterized catalog statements."""

    def __init__(self, rows=None, tag_rows=None) -> None:
        self.calls: list[tuple[str, object]] = []
        self.rows = list(rows or [])
        self.tag_rows = list(tag_rows or [])
        self._current_rows = self.rows

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, statement: str, params=None) -> None:
        self.calls.append((statement, params))
        self._current_rows = self.tag_rows if "FROM model_serving_tag AS mst" in statement else self.rows

    def fetchall(self):
        return list(self._current_rows)


class _FakeConnection:
    """Minimal transaction object exercising the PostgreSQL adapter."""

    def __init__(self, rows=None, tag_rows=None) -> None:
        self.cursor_object = _FakeCursor(rows, tag_rows)
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def cursor(self):
        return self.cursor_object

    def commit(self) -> None:
        self.commits += 1


def test_postgres_success_is_parameterized_and_failure_does_not_disable_lkg() -> None:
    """PostgreSQL success replaces rows; failure records evidence only."""
    source = _source()
    connections: list[_FakeConnection] = []

    def factory():
        connection = _FakeConnection()
        connections.append(connection)
        return connection

    store = PostgresProviderCatalogStore(
        "postgresql://catalog.example/db",
        connection_factory=factory,
    )
    store.record_success(
        source,
        [_model(source, "model-a")],
        eligible_model_ids={"model-a"},
        serving_tags={"model-a": ("discovered", "chat")},
    )
    success_sql = "\n".join(
        statement for statement, _params in connections[-1].cursor_object.calls
    )
    assert "UPDATE provider_model SET enabled_flag = false" in success_sql
    assert "INSERT INTO model_serving_tag" in success_sql
    assert connections[-1].commits >= 1

    store.record_failure(source, error_code="provider_timeout: secret-token")
    failure_sql = "\n".join(
        statement for statement, _params in connections[-1].cursor_object.calls
    )
    assert "UPDATE provider_model SET enabled_flag = false" not in failure_sql
    assert "INSERT INTO catalog_refresh_run" in failure_sql
    assert store.refresh_evidence()[-1].error_code == "unknown_error"


def test_postgres_success_clears_tags_account_wide_not_per_current_model() -> None:
    """A model absent from a fresh refresh cannot leave orphaned serving_tag rows."""
    source = _source()
    connection = _FakeConnection()
    store = PostgresProviderCatalogStore(
        "postgresql://catalog.example/db",
        connection_factory=lambda: connection,
    )
    store.record_success(
        source,
        [_model(source, "model-a")],
        eligible_model_ids={"model-a"},
        serving_tags={"model-a": ("discovered", "chat")},
    )
    statements = [statement for statement, _params in connection.cursor_object.calls]
    tag_delete_index = next(
        i for i, s in enumerate(statements) if "DELETE FROM model_serving_tag" in s
    )
    tag_insert_index = next(
        i for i, s in enumerate(statements) if "INSERT INTO model_serving_tag" in s
    )
    assert "WHERE provider_model_id IN" in statements[tag_delete_index]
    assert "WHERE provider_account_id = %s" in statements[tag_delete_index]
    assert tag_delete_index < tag_insert_index
    assert statements.count(
        "DELETE FROM model_serving_tag WHERE provider_model_id = %s"
    ) == 0


def test_postgres_serving_models_reconstructs_account_scoped_rows() -> None:
    """Read-side rows become normalized DiscoveredModel records."""
    source = _source(provider="openrouter", credential="OPENROUTER_API_KEY")
    connection = _FakeConnection(
        [
            (
                "model-b",
                source.chat_base_url,
                "Bearer",
                Decimal("0.25"),
                Decimal("0.50"),
                "usd",
            )
        ],
        [
            ("model-b", "chat"),
            ("model-b", "capability:chat"),
            ("model-b", "cost:free"),
            ("model-b", "input:text"),
        ],
    )
    store = PostgresProviderCatalogStore(
        "postgresql://catalog.example/db",
        connection_factory=lambda: connection,
    )
    assert store.serving_models(source) == [
        DiscoveredModel(
            provider_name="openrouter",
            model_id="model-b",
            credential_name="OPENROUTER_API_KEY",
            chat_base_url=source.chat_base_url,
            auth_scheme="Bearer",
            prompt_price_per_1k=0.25,
            completion_price_per_1k=0.5,
            currency_code="USD",
            capabilities=("chat",),
            input_modalities=("text",),
            is_free=True,
        )
    ]
    model_query, model_params = connection.cursor_object.calls[-2]
    tag_query, tag_params = connection.cursor_object.calls[-1]
    assert "JOIN provider_account AS pa" in model_query
    assert "FROM model_serving_tag AS mst" in tag_query
    assert "serving_eligible_flag = true" in model_query
    assert model_params == tag_params == (provider_account_id(source),)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
