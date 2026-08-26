"""Boundary tests for durable provider-catalog bootstrap error paths."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

import contextual_orchestrator.provider_catalog_bootstrap as pcb
from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    PostgresCredentialBackend,
    get_backend,
    get_credential,
    set_backend,
)
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    ProviderModelSource,
)
from contextual_orchestrator.provider_bootstrap import (
    PROVIDER_CREDENTIAL_NAMES,
    ProviderBootstrapError,
)
from contextual_orchestrator.provider_catalog_bootstrap import (
    ProviderCatalogSnapshot,
    _restore_provider_credentials_atomically,
    bootstrap_provider_catalog_runtime,
    build_provider_catalog_store,
)


def _environment() -> dict[str, str]:
    return {
        name: f"value-for-{name.casefold()}"
        for name in PROVIDER_CREDENTIAL_NAMES
    }


def _source(provider: str, credential: str) -> ProviderModelSource:
    return ProviderModelSource(
        provider_name=provider,
        credential_name=credential,
        list_url=f"https://{provider}.example/v1/models",
        chat_base_url=f"https://{provider}.example/v1",
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


class _StubCatalogStore:
    """Adversarial catalog store returning non-chat serving rows."""

    backend_name = "stub"

    def __init__(self, models: list[DiscoveredModel]) -> None:
        self._models = models

    def record_success(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def record_failure(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def serving_models(self, _source: ProviderModelSource) -> list[DiscoveredModel]:
        return list(self._models)

    def refresh_evidence(self) -> tuple[Any, ...]:
        return ()


# --- build_provider_catalog_store -------------------------------------------------


def test_build_store_selects_memory_for_in_memory_backend() -> None:
    from contextual_orchestrator.provider_catalog_store import (
        InMemoryProviderCatalogStore,
    )

    set_backend(InMemoryCredentialBackend())
    try:
        assert isinstance(build_provider_catalog_store(), InMemoryProviderCatalogStore)
    finally:
        set_backend(None)


def test_build_store_selects_postgres_for_postgres_backend() -> None:
    from contextual_orchestrator.provider_catalog_store import (
        PostgresProviderCatalogStore,
    )

    backend = PostgresCredentialBackend(
        "postgresql://registry_user@localhost/registry_db", "passphrase"
    )
    set_backend(backend)
    try:
        store = build_provider_catalog_store()
        assert isinstance(store, PostgresProviderCatalogStore)
    finally:
        set_backend(None)


def test_build_store_rejects_foreign_backend() -> None:
    class AlienBackend:
        pass

    set_backend(AlienBackend())  # type: ignore[arg-type]
    try:
        with pytest.raises(ProviderBootstrapError, match="atomic credential backend"):
            build_provider_catalog_store()
    finally:
        set_backend(None)


def test_restore_rejects_foreign_backend_during_rollback() -> None:
    class AlienBackend:
        pass

    set_backend(AlienBackend())  # type: ignore[arg-type]
    try:
        with pytest.raises(ProviderBootstrapError, match="rollback requires"):
            _restore_provider_credentials_atomically({"OPENAI_API_KEY": "prior"})
    finally:
        set_backend(None)


# --- Postgres rollback transaction ------------------------------------------------


class _FakeCursor:
    def __init__(self, log: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._log = log

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self._log.append((sql.split()[0], params))

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None


class _FakeConnection:
    def __init__(self, log: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._log = log
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._log)

    def commit(self) -> None:
        self.commits += 1


class _StubPostgresBackend(PostgresCredentialBackend):
    """Offline Postgres credential backend recording rollback statements."""

    def __init__(self) -> None:
        super().__init__("postgresql://rollback_user@localhost/registry_db", "phrase")
        self.log: list[tuple[str, tuple[Any, ...]]] = []
        self.connection = _FakeConnection(self.log)

    def _connect(self) -> Any:
        @contextmanager
        def _cm() -> Iterator[_FakeConnection]:
            yield self.connection

        return _cm()

    def _ensure_schema(self, connection: object) -> None:
        return None


def test_restore_postgres_backend_deletes_and_upserts_atomically() -> None:
    backend = _StubPostgresBackend()
    set_backend(backend)
    try:
        restored = _restore_provider_credentials_atomically({
            "AAA_KEY": None,
            "BBB_KEY": "previous-secret",
        })
        assert restored == ("AAA_KEY", "BBB_KEY")
        operations = [op for op, _params in backend.log]
        assert operations == ["DELETE", "INSERT"]
        delete_params = backend.log[0][1]
        upsert_params = backend.log[1][1]
        assert delete_params == ("AAA_KEY",)
        # The prior value and the backend passphrase travel together for pgcrypto.
        assert upsert_params[:2] == ("BBB_KEY", "previous-secret")
        assert upsert_params[2] == "phrase"
        assert backend.connection.commits == 1
    finally:
        set_backend(None)


# --- runtime failure and skip paths -----------------------------------------------


def test_runtime_skips_sources_without_registered_credential() -> None:
    openai = _source("openai", "OPENAI_API_KEY")
    orphan = _source("together", "TOGETHER_API_KEY")
    store = InMemoryStoreShim()
    set_backend(InMemoryCredentialBackend())
    try:
        report = bootstrap_provider_catalog_runtime(
            environ={"OPENAI_API_KEY": "only-openai"},
            require_all_credentials=False,
            catalog_store=store,
            sources=(openai, orphan),
            discovery=lambda _sources: ([_model(openai, "gpt-live")], []),
            model_limit=4,
        )
        # The unregistered source contributes no model and no refresh evidence.
        assert report.catalog_model_count == 1
        assert report.selected_agent_ids == ("openai_gpt_live",)
        assert report.providers_with_errors == ()
        assert report.catalog_refresh_failure_count == 0
        refreshes = report.as_dict()["catalog_refreshes"]
        assert isinstance(refreshes, list)
        assert len(refreshes) == 1
        assert refreshes[0]["provider_account_id"] == "openai_openai_api_key"
        assert refreshes[0]["refresh_status"] == "succeeded"
        assert len(store.refresh_evidence()) == 1  # only the registered account
        assert get_credential("TOGETHER_API_KEY") is None
    finally:
        set_backend(None)


class InMemoryStoreShim:
    """Minimal catalog store delegating persistence to an in-memory store."""

    def __init__(self) -> None:
        self._inner = _make_memory_store()
        self.backend_name = self._inner.backend_name

    def record_success(self, *args: Any, **kwargs: Any) -> None:
        self._inner.record_success(*args, **kwargs)

    def record_failure(self, *args: Any, **kwargs: Any) -> None:
        self._inner.record_failure(*args, **kwargs)

    def serving_models(self, source: ProviderModelSource) -> list[DiscoveredModel]:
        return self._inner.serving_models(source)

    def refresh_evidence(self) -> tuple[Any, ...]:
        return self._inner.refresh_evidence()


def _make_memory_store() -> Any:
    from contextual_orchestrator.provider_catalog_store import (
        InMemoryProviderCatalogStore,
    )

    return InMemoryProviderCatalogStore()


def test_runtime_raises_when_selection_returns_empty_for_nonchat_rows() -> None:
    """A catalog store serving only guard-class rows must fail closed."""
    openai = _source("openai", "OPENAI_API_KEY")
    guard_only = _StubCatalogStore([_model(openai, "llama-guard-3-8b")])
    set_backend(InMemoryCredentialBackend())
    try:
        with pytest.raises(
            ProviderBootstrapError, match="selected no persisted chat-compatible"
        ):
            bootstrap_provider_catalog_runtime(
                environ=_environment(),
                catalog_store=guard_only,
                sources=(openai,),
                discovery=lambda _sources: ([_model(openai, "llama-guard-3-8b")], []),
                model_limit=4,
            )
        # Rollback removed the registered secret after the failed selection.
        assert get_credential("OPENAI_API_KEY") is None
    finally:
        set_backend(None)


def test_runtime_wraps_failed_rollback_into_bootstrap_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_rollback(_previous: Any) -> tuple[str, ...]:
        raise RuntimeError("storage engine vanished")

    monkeypatch.setattr(pcb, "_restore_provider_credentials_atomically", broken_rollback)
    openai = _source("openai", "OPENAI_API_KEY")
    set_backend(InMemoryCredentialBackend())
    try:
        with pytest.raises(
            ProviderBootstrapError, match="credential rollback could not complete"
        ) as excinfo:
            bootstrap_provider_catalog_runtime(
                environ=_environment(),
                catalog_store=_make_memory_store(),
                sources=(openai,),
                discovery=lambda _sources: ([], []),  # empty discovery fails the run
                model_limit=4,
            )
        assert isinstance(excinfo.value.__cause__, RuntimeError)
    finally:
        set_backend(None)


# --- CLI boundary ------------------------------------------------------------------


def test_main_prints_secret_free_report_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in PROVIDER_CREDENTIAL_NAMES:
        monkeypatch.setenv(name, f"value-for-{name.casefold()}")

    openai = _source("openai", "OPENAI_API_KEY")
    openrouter = _source("openrouter", "OPENROUTER_API_KEY")
    nim = _source("nvidia_nim", "NVIDIA_NIM_API_KEY")

    def fake_discovery(sources: Any) -> tuple[list[DiscoveredModel], list[Any]]:
        by_provider = {s.provider_name: s for s in sources}
        return [
            _model(by_provider["openai"], "gpt-live"),
            _model(by_provider["openrouter"], "router-live"),
            _model(by_provider["nvidia_nim"], "nim-live"),
        ], []

    monkeypatch.setattr(pcb, "discover_all_models", fake_discovery)
    pcb.main(["--model-limit", "3"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["catalog_model_count"] == 3
    assert payload["durable_agent_pool"] is False
    serialized = json.dumps(payload)
    assert "value-for-" not in serialized  # secrets never reach stdout


def test_main_allow_partial_flag_runs_subset_inventory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "only-openai-present")

    openai = _source("openai", "OPENAI_API_KEY")
    monkeypatch.setattr(
        pcb,
        "discover_all_models",
        lambda sources: ([_model(sources[0], "gpt-live")], []),
    )
    pcb.main(["--allow-partial-credentials"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["registered_credentials"] == ["OPENAI_API_KEY"]


def test_main_requires_inventory_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in PROVIDER_CREDENTIAL_NAMES:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProviderBootstrapError, match="complete credential inventory"):
        pcb.main([])
