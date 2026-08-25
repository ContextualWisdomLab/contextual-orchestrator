"""Boundary coverage for provider catalog persistence and normalization guards.

Every test here exercises an error path, degenerate input, or concurrency
branch that the ordinary success-path tests cannot reach: incomplete account
identities, non-finite/unparseable prices, unknown currencies, malformed
error codes, invalid serving tags, empty refresh payloads, DSN validation,
the packaging-boundary psycopg import, and the double-checked schema lock.
"""

from __future__ import annotations

import sys
import threading
import types

import pytest

from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    ProviderModelSource,
)
from contextual_orchestrator.provider_catalog_store import (
    InMemoryProviderCatalogStore,
    PostgresProviderCatalogStore,
    ProviderCatalogError,
    normalize_discovered_model,
    provider_account_id,
    provider_model_id,
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


def test_account_identity_requires_both_provider_and_credential_words() -> None:
    """An account id must never silently collapse to a single-word slug."""
    blank_provider = replace_source(provider_name="   ")
    blank_credential = replace_source(credential_name="!!!")
    with pytest.raises(ProviderCatalogError, match="identity is incomplete"):
        provider_account_id(blank_provider)
    with pytest.raises(ProviderCatalogError, match="identity is incomplete"):
        provider_account_id(blank_credential)


def replace_source(**overrides: str) -> ProviderModelSource:
    base = _source()
    fields = {
        "provider_name": base.provider_name,
        "credential_name": base.credential_name,
        "list_url": base.list_url,
        "chat_base_url": base.chat_base_url,
    }
    fields.update(overrides)
    return ProviderModelSource(**fields)


def test_model_identity_rejects_blank_names() -> None:
    """Both identity helpers refuse whitespace-only model names."""
    source = _source()
    with pytest.raises(ProviderCatalogError, match="provider model name is empty"):
        provider_model_id(source, "   ")
    with pytest.raises(ProviderCatalogError, match="provider model name is empty"):
        normalize_discovered_model(source, _model(source, "\t\n"))


def test_normalize_price_rejects_none_bool_and_unparseable_values() -> None:
    """None, booleans, and unparseable text normalize to unknown price."""
    source = _source()
    for bad_price in (None, True, False, "definitely-not-a-price"):
        normalized = normalize_discovered_model(source, _model(source, "m", bad_price))
        assert normalized.prompt_price_per_1k is None
        assert normalized.completion_price_per_1k is None


def test_normalize_currency_rejects_non_string_codes() -> None:
    """A numeric currency code must become the explicit unknown marker."""
    source = _source()
    normalized = normalize_discovered_model(source, _model(source, "m", 2.0))
    normalized_with_bad_currency = type(normalized)(
        **{
            **normalized.__dict__,
            "currency_code": 42,
        }
    )
    from contextual_orchestrator.provider_catalog_store import _normalize_currency

    assert _normalize_currency(42) == "UNKNOWN"
    assert _normalize_currency(None) == "UNKNOWN"
    assert _normalize_currency("  jpy ") == "JPY"
    del normalized_with_bad_currency


@pytest.mark.parametrize("bad_code", [42, None, b"usd"])
def test_failure_error_code_falls_back_to_unknown_for_non_strings(bad_code) -> None:
    """record_failure normalizes hostile error codes into the approved set."""
    store = InMemoryProviderCatalogStore()
    source = _source()
    store.record_success(
        source,
        [_model(source, "model-a")],
        eligible_model_ids={"model-a"},
        serving_tags={},
    )
    store.record_failure(source, error_code=bad_code)
    evidence = store.refresh_evidence()[-1]
    assert evidence.refresh_status == "failed"
    assert evidence.error_code == "unknown_error"


def test_serving_tag_normalization_drops_non_strings_and_invalid_patterns() -> None:
    """Only lowercase identifier-shaped tags survive normalization."""
    store = InMemoryProviderCatalogStore()
    source = _source()
    store.record_success(
        source,
        [_model(source, "model-a")],
        eligible_model_ids={"model-a"},
        serving_tags={
            "model-a": (42, None, "!!!bad-tag", "9leading", "", "chat", "Chat ")
        },
    )
    assert store.serving_tags(source, "model-a") == ("chat",)
    # A model with no recorded tags at all returns an empty tuple.
    assert store.serving_tags(_source(provider="other"), "model-a") == ()


def test_postgres_store_validates_dsn_and_reports_backend() -> None:
    """Empty or non-string DSNs are rejected before any connection attempt."""
    with pytest.raises(ProviderCatalogError, match="requires a PostgreSQL DSN"):
        PostgresProviderCatalogStore("")
    with pytest.raises(ProviderCatalogError, match="requires a PostgreSQL DSN"):
        PostgresProviderCatalogStore(None)  # type: ignore[arg-type]
    assert PostgresProviderCatalogStore("postgresql://db.example/x").backend_name == (
        "postgres"
    )


def test_connect_without_factory_uses_packaged_psycopg(monkeypatch) -> None:
    """The default transport imports psycopg lazily and passes through the DSN."""
    sentinel_connection = object()
    calls: list[str] = []

    fake_psycopg = types.ModuleType("psycopg")

    def fake_connect(dsn: str):
        calls.append(dsn)
        return sentinel_connection

    fake_psycopg.connect = fake_connect  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    store = PostgresProviderCatalogStore("postgresql://lazy.example/db")
    assert store._connect() is sentinel_connection
    assert calls == ["postgresql://lazy.example/db"]


class _SchemaLockFakeCursor:
    """Cursor whose DDL execution blocks until released by the test."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, statement: str, params=None) -> None:
        self.calls.append((statement, params))

    def fetchall(self):
        return []


class _SchemaLockFakeConnection:
    """Connection that blocks inside commit while holding the schema lock."""

    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        self.cursor_object = _SchemaLockFakeCursor()
        self.entered = entered
        self.release = release
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def cursor(self):
        return self.cursor_object

    def commit(self) -> None:
        if not self.entered.is_set():
            self.entered.set()
            assert self.release.wait(timeout=10)
        self.commits += 1


def test_double_checked_schema_lock_runs_ddl_exactly_once() -> None:
    """A second connection entering the lock sees the schema as ready."""
    entered = threading.Event()
    release = threading.Event()
    connections: list[_SchemaLockFakeConnection] = []
    lock = threading.Lock()

    def factory() -> _SchemaLockFakeConnection:
        with lock:
            connection = _SchemaLockFakeConnection(entered, release)
            connections.append(connection)
            return connection

    store = PostgresProviderCatalogStore(
        "postgresql://catalog.example/db",
        connection_factory=factory,
    )
    source = _source()

    first_ready = threading.Event()

    def writer() -> None:
        store.record_success(
            source,
            [_model(source, "model-a")],
            eligible_model_ids={"model-a"},
            serving_tags={},
        )
        first_ready.set()

    thread_a = threading.Thread(target=writer, name="schema-writer")
    thread_a.start()
    assert entered.wait(timeout=10)

    read_results: list[list[DiscoveredModel]] = []

    def reader() -> None:
        read_results.append(store.serving_models(source))

    thread_b = threading.Thread(target=reader, name="schema-reader")
    thread_b.start()
    # Give the reader time to block on the schema lock before releasing it.
    deadline = threading.Event()
    assert not deadline.wait(timeout=0.3)

    release.set()
    thread_b.join(timeout=10)
    release.set()
    thread_a.join(timeout=10)
    assert first_ready.is_set()
    assert read_results == [[]]

    ddl_statements = [
        statement
        for connection in connections
        for statement, _params in connection.cursor_object.calls
        if "CREATE TABLE" in statement
    ]
    assert len(ddl_statements) == 1


def test_empty_successful_refresh_is_rejected_before_writes() -> None:
    """Both stores refuse to persist an empty 'successful' catalog."""
    source = _source()

    memory = InMemoryProviderCatalogStore()
    with pytest.raises(ProviderCatalogError, match="cannot be empty"):
        memory.record_success(
            source, [], eligible_model_ids=set(), serving_tags={}
        )

    postgres = PostgresProviderCatalogStore(
        "postgresql://catalog.example/db",
        connection_factory=lambda: pytest.fail("no connection may be opened"),
    )
    with pytest.raises(ProviderCatalogError, match="cannot be empty"):
        postgres.record_success(
            source, [], eligible_model_ids=set(), serving_tags={}
        )


def test_mixed_eligibility_skips_tag_inserts_for_uneligible_models() -> None:
    """Models outside the eligible set never receive serving-tag rows."""
    source = _source()
    connection_calls: list[tuple[str, object]] = []

    class RecordingCursor(_SchemaLockFakeCursor):
        def execute(self, statement: str, params=None) -> None:
            super().execute(statement, params)
            connection_calls.append((statement, params))

    class RecordingConnection:
        def __init__(self) -> None:
            self.cursor_object = RecordingCursor()
            self.commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def cursor(self):
            return self.cursor_object

        def commit(self) -> None:
            self.commits += 1

    store = PostgresProviderCatalogStore(
        "postgresql://catalog.example/db",
        connection_factory=lambda: RecordingConnection(),
    )
    store.record_success(
        source,
        [_model(source, "eligible-model"), _model(source, "bench-only-model")],
        eligible_model_ids={"eligible-model"},
        serving_tags={"eligible-model": ("chat",), "bench-only-model": ("chat",)},
    )
    tag_inserts = [
        params
        for statement, params in connection_calls
        if "INSERT INTO model_serving_tag" in statement
    ]
    eligible_row_id = provider_model_id(source, "eligible-model")
    bench_row_id = provider_model_id(source, "bench-only-model")
    assert all(params[0] == eligible_row_id for params in tag_inserts)
    assert all(params[0] != bench_row_id for params in tag_inserts)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
