"""Boundary tests for provider bootstrap credential, selection, and pool paths."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import pytest

import contextual_orchestrator.provider_bootstrap as pb
from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    PostgresCredentialBackend,
    get_credential,
    set_backend,
)
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator.provider_bootstrap import (
    PROVIDER_CREDENTIAL_NAMES,
    ProviderBootstrapError,
    collect_provider_credentials,
    register_provider_credentials_atomically,
    select_provider_diverse_models,
)


def _complete_environment() -> dict[str, str]:
    return {
        name: f"secret-for-{name.lower()}\n"
        for name in PROVIDER_CREDENTIAL_NAMES
    }


def _model(
    provider: str,
    credential: str,
    model_id: str,
    prompt: float | None = 1.0,
    currency: str = "USD",
) -> DiscoveredModel:
    return DiscoveredModel(
        provider_name=provider,
        model_id=model_id,
        credential_name=credential,
        chat_base_url=f"https://{provider}.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=prompt,
        completion_price_per_1k=prompt,
        currency_code=currency,
    )


# --- collect_provider_credentials --------------------------------------------------


def test_collect_partial_mode_with_zero_values_fails_closed() -> None:
    with pytest.raises(ProviderBootstrapError, match="received no credentials"):
        collect_provider_credentials({}, require_all=False)


# --- register_provider_credentials_atomically ---------------------------------------


def test_register_rejects_empty_batch() -> None:
    set_backend(InMemoryCredentialBackend())
    try:
        with pytest.raises(ProviderBootstrapError, match="empty credential batch"):
            register_provider_credentials_atomically({})
    finally:
        set_backend(None)


def test_register_rejects_unknown_credential_names() -> None:
    set_backend(InMemoryCredentialBackend())
    try:
        with pytest.raises(ProviderBootstrapError, match="unknown credential names"):
            register_provider_credentials_atomically({"MADE_UP_KEY": "value"})
    finally:
        set_backend(None)


def test_register_rejects_non_string_value() -> None:
    set_backend(InMemoryCredentialBackend())
    try:
        with pytest.raises(ProviderBootstrapError, match="rejected an empty value"):
            register_provider_credentials_atomically({"OPENAI_API_KEY": 123})  # type: ignore[dict-item]
    finally:
        set_backend(None)


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
    def __init__(self) -> None:
        self.log: list[tuple[str, tuple[Any, ...]]] = []
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.log)

    def commit(self) -> None:
        self.commits += 1


class _StubPostgresBackend(PostgresCredentialBackend):
    """Offline pgcrypto backend recording registration statements."""

    def __init__(self) -> None:
        super().__init__("postgresql://registry_user@localhost/registry_db", "phrase")
        self.connection = _FakeConnection()

    def _connect(self) -> Any:
        connection = self.connection

        @contextmanager
        def _cm() -> Iterator[_FakeConnection]:
            yield connection

        return _cm()

    def _ensure_schema(self, connection: object) -> None:
        return None


def test_register_postgres_backend_upserts_every_credential_in_one_transaction() -> None:
    backend = _StubPostgresBackend()
    set_backend(backend)
    try:
        registered = register_provider_credentials_atomically({
            "NVIDIA_NIM_API_KEY_SUB": "second\n",
            "OPENAI_API_KEY": "first",
        })
        assert registered == ("NVIDIA_NIM_API_KEY_SUB", "OPENAI_API_KEY")
        operations = [op for op, _params in backend.connection.log]
        assert operations == ["INSERT", "INSERT"]
        assert backend.connection.commits == 1
        first_params = backend.connection.log[0][1]
        # Values are line-ending-normalized before encryption transport.
        assert first_params[:2] == ("NVIDIA_NIM_API_KEY_SUB", "second")
        assert first_params[2] == "phrase"
    finally:
        set_backend(None)


def test_register_requires_atomic_builtin_backend() -> None:
    class AlienBackend:
        pass

    set_backend(AlienBackend())  # type: ignore[arg-type]
    try:
        with pytest.raises(ProviderBootstrapError, match="atomic built-in credential backend"):
            register_provider_credentials_atomically({"OPENAI_API_KEY": "value"})
    finally:
        set_backend(None)


# --- select_provider_diverse_models -------------------------------------------------


def test_select_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        select_provider_diverse_models([_model("openai", "OPENAI_API_KEY", "gpt-x")], limit=0)


def test_select_unpriced_and_foreign_currency_models_sort_last_but_still_fill() -> None:
    priced = _model("openai", "OPENAI_API_KEY", "gpt-cheap", prompt=0.5)
    unpriced = _model("openrouter", "OPENROUTER_API_KEY", "qwen-free", prompt=None)
    eur = _model("nvidia_nim", "NVIDIA_NIM_API_KEY", "nim-eur", prompt=0.01, currency="EUR")

    selected = select_provider_diverse_models(
        [unpriced, eur, priced], limit=3
    )
    # Known USD pricing wins the diversity slot; unknown/incomparable fill after.
    assert [m.model_id for m in selected][:1] == ["gpt-cheap"]
    assert {m.model_id for m in selected} == {"gpt-cheap", "qwen-free", "nim-eur"}


def test_select_fills_remaining_slots_from_same_provider_family() -> None:
    primary = _model(
        "nvidia_nim", "NVIDIA_NIM_API_KEY", "nim-gamma", prompt=3.0
    )
    same_family_sub = _model(
        "nvidia_nim_sub", "NVIDIA_NIM_API_KEY_SUB", "nim-delta", prompt=4.0
    )
    selected = select_provider_diverse_models([primary, same_family_sub], limit=2)
    # Both credentials share the nvidia_nim outage family, so diversity yields
    # one slot and the filler loop backfills the second from the same family.
    assert [m.model_id for m in selected] == ["nim-gamma", "nim-delta"]


def test_select_skips_non_chat_candidates_entirely() -> None:
    guard = _model("openai", "OPENAI_API_KEY", "llama-guard-4b", prompt=0.1)
    chat = _model("openrouter", "OPENROUTER_API_KEY", "qwen-chat", prompt=9.0)
    selected = select_provider_diverse_models([guard, chat], limit=5)
    assert [m.model_id for m in selected] == ["qwen-chat"]


# --- bootstrap_provider_runtime ------------------------------------------------------


def test_runtime_fails_when_discovery_returns_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pb, "discover_all_models", lambda: ([], []))
    set_backend(InMemoryCredentialBackend())
    try:
        with pytest.raises(ProviderBootstrapError, match="discovered no usable models"):
            pb.bootstrap_provider_runtime(environ=_complete_environment(), model_limit=2)
    finally:
        set_backend(None)


def test_runtime_reports_pricing_and_error_providers_without_agents_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextual_orchestrator.model_discovery import ProviderDiscoveryError

    good = _model("openai", "OPENAI_API_KEY", "gpt-live", prompt=1.5)
    failed = _model("bytez", "BYTEZ_API_KEY", "bytez-live", prompt=0.25)

    def discovery() -> tuple[list[DiscoveredModel], list[ProviderDiscoveryError]]:
        return [good, failed], [ProviderDiscoveryError("together", "http_401")]

    monkeypatch.setattr(pb, "discover_all_models", discovery)
    set_backend(InMemoryCredentialBackend())
    try:
        report = pb.bootstrap_provider_runtime(
            environ=_complete_environment(), model_limit=8
        )
        payload = report.as_dict()
        assert payload["durable_agent_pool"] is False
        assert payload["enabled_agent_ids"] == []
        assert payload["providers_with_errors"] == ["together"]
        assert payload["eligible_model_count"] == 2
        assert payload["priced_model_count"] >= 1
        serialized = str(payload)
        assert "secret-for-" not in serialized
        assert all(get_credential(name) for name in PROVIDER_CREDENTIAL_NAMES)
    finally:
        set_backend(None)


def test_register_rejects_whitespace_only_value() -> None:
    set_backend(InMemoryCredentialBackend())
    try:
        with pytest.raises(ProviderBootstrapError, match="rejected an empty value"):
            register_provider_credentials_atomically({"OPENAI_API_KEY": "  \r\n "})
    finally:
        set_backend(None)


def test_select_returns_partial_pool_when_family_exhausted_below_limit() -> None:
    primary = _model("nvidia_nim", "NVIDIA_NIM_API_KEY", "nim-primary", prompt=1.0)
    sibling = _model(
        "nvidia_nim_sub", "NVIDIA_NIM_API_KEY_SUB", "nim-sibling", prompt=2.0
    )
    # Only one outage family exists, so diversity yields one slot, the filler
    # adds the second, and the pool legitimately ends below ``limit``.
    selected = select_provider_diverse_models([primary, sibling], limit=5)
    assert [m.model_id for m in selected] == ["nim-primary", "nim-sibling"]


def test_durable_pool_sync_keeps_manual_agents_and_disabled_leftovers(
    tmp_path: Any,
) -> None:
    """Non-discovered operators survive cleanup; disabled leftovers stay put."""
    from contextual_orchestrator import ModelAgent, TaskOrchestrator
    from dataclasses import replace as dc_replace
    from contextual_orchestrator.provider_bootstrap import (
        _synchronize_durable_agent_pool,
    )

    agents_db = str(tmp_path / "pool_boundary.db")
    seed = TaskOrchestrator(
        [ModelAgent("seed_placeholder_agent", "placeholder-model")],
        agents_db=agents_db,
    )
    # Construction does not persist; sync_discovered_agents is the durable upsert.
    seed.sync_discovered_agents([
        ModelAgent("manual_operator_agent", "manual-model", tags=("manual",)),
        dc_replace(
            ModelAgent("openai_retired_model", "retired-model", tags=("discovered",)),
            disabled=True,
        ),
    ])

    selected_models = [
        _model("openai", "OPENAI_API_KEY", "gpt-current"),
        _model("openrouter", "OPENROUTER_API_KEY", "qwen-current"),
    ]

    enabled = _synchronize_durable_agent_pool(agents_db, selected_models)

    assert enabled == ("openai_gpt_current", "openrouter_qwen_current")
    restarted = TaskOrchestrator([], agents_db=agents_db)
    ids_by_state = {
        agent.id: ("disabled" if agent.disabled else "enabled")
        for agent in restarted.candidates
    }
    # The manual operator survives untouched; the disabled discovered leftover
    # is neither activated nor deleted.
    assert ids_by_state["manual_operator_agent"] == "enabled"
    assert ids_by_state["openai_retired_model"] == "disabled"
    assert ids_by_state["openai_gpt_current"] == "enabled"
    assert ids_by_state["openrouter_qwen_current"] == "enabled"


def test_durable_pool_sync_closes_temporary_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """A refresh must stop telemetry owned by its temporary orchestrator."""
    from contextual_orchestrator import TaskOrchestrator
    from contextual_orchestrator.provider_bootstrap import (
        _synchronize_durable_agent_pool,
    )

    closed: list[bool] = []

    class TrackingOrchestrator(TaskOrchestrator):
        def close(self) -> None:
            closed.append(True)
            super().close()

    monkeypatch.setattr(pb, "TaskOrchestrator", TrackingOrchestrator)
    enabled = _synchronize_durable_agent_pool(
        str(tmp_path / "pool_close.db"),
        [_model("openrouter", "OPENROUTER_API_KEY", "qwen-current")],
    )

    assert enabled == ("openrouter_qwen_current",)
    assert closed == [True]
