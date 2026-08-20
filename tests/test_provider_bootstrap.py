"""Contracts for durable all-provider bootstrap and provider-diverse model activation."""

from __future__ import annotations

from dataclasses import replace
import json
import os

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    get_credential,
    set_backend,
)
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    agent_from_discovered,
)
from contextual_orchestrator import provider_bootstrap


@pytest.fixture(autouse=True)
def isolated_credential_backend():
    """Give each test a fresh process-local credential registry."""
    set_backend(InMemoryCredentialBackend())
    yield
    set_backend(None)


def _complete_environment() -> dict[str, str]:
    return {
        name: f"secret-for-{name.lower()}\n"
        for name in provider_bootstrap.PROVIDER_CREDENTIAL_NAMES
    }


def _model(
    provider: str,
    credential: str,
    model_id: str,
    prompt: float | None,
) -> DiscoveredModel:
    return DiscoveredModel(
        provider_name=provider,
        model_id=model_id,
        credential_name=credential,
        chat_base_url=f"https://{provider}.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=prompt,
        completion_price_per_1k=prompt,
    )


def test_fixed_inventory_matches_all_five_organization_secrets():
    """The bootstrap inventory must not silently lose an organization provider key."""
    assert set(provider_bootstrap.PROVIDER_CREDENTIAL_NAMES) == {
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "BYTEZ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    }


def test_collect_requires_complete_inventory_without_leaking_values():
    """Production bootstrap fails before writes when one trusted secret is absent."""
    environment = _complete_environment()
    removed = environment.pop("BYTEZ_API_KEY")
    with pytest.raises(provider_bootstrap.ProviderBootstrapError) as raised:
        provider_bootstrap.collect_provider_credentials(environment)
    assert "BYTEZ_API_KEY" in str(raised.value)
    assert removed.strip() not in str(raised.value)
    assert all(
        get_credential(name) is None
        for name in provider_bootstrap.PROVIDER_CREDENTIAL_NAMES
    )


def test_atomic_memory_registration_strips_mounted_secret_newlines():
    """A complete inventory becomes visible together and mounted newlines are removed."""
    credentials = provider_bootstrap.collect_provider_credentials(
        _complete_environment()
    )
    registered = provider_bootstrap.register_provider_credentials_atomically(
        credentials
    )
    assert registered == tuple(
        sorted(provider_bootstrap.PROVIDER_CREDENTIAL_NAMES)
    )
    for name in provider_bootstrap.PROVIDER_CREDENTIAL_NAMES:
        value = get_credential(name)
        assert value == f"secret-for-{name.lower()}"
        assert "\n" not in value


def test_unknown_credential_name_is_rejected_before_any_write():
    """The fixed bootstrap boundary cannot be expanded by untrusted environment names."""
    with pytest.raises(provider_bootstrap.ProviderBootstrapError):
        provider_bootstrap.register_provider_credentials_atomically(
            {"EVIL_PROVIDER_KEY": "secret"}
        )
    assert get_credential("EVIL_PROVIDER_KEY") is None


def test_diverse_selection_prefers_known_cost_without_treating_unknown_as_free():
    """Unknown-cost Bytez candidates stay usable but cannot win as fabricated zero cost."""
    models = [
        _model("openai", "OPENAI_API_KEY", "gpt-expensive", 4.0),
        _model("openai", "OPENAI_API_KEY", "gpt-cheap", 1.0),
        _model("openrouter", "OPENROUTER_API_KEY", "mistral-router", 2.0),
        _model("bytez", "BYTEZ_API_KEY", "llama-unknown", None),
    ]
    selected = provider_bootstrap.select_provider_diverse_models(
        models,
        limit=3,
    )
    assert [
        (item.provider_name, item.model_id)
        for item in selected
    ] == [
        ("openai", "gpt-cheap"),
        ("openrouter", "mistral-router"),
        ("bytez", "llama-unknown"),
    ]


def test_non_chat_catalog_rows_are_never_selected_for_chat_service():
    """Embeddings, rerankers, speech, image, moderation, and realtime rows stay inert."""
    models = [
        _model("openai", "OPENAI_API_KEY", "text-embedding-3-small", 0.1),
        _model("openai", "OPENAI_API_KEY", "whisper-1", 0.1),
        _model("openai", "OPENAI_API_KEY", "gpt-image-1", 0.1),
        _model("openai", "OPENAI_API_KEY", "omni-moderation-latest", 0.1),
        _model("nvidia_nim", "NVIDIA_NIM_API_KEY", "nv-rerankqa-mistral-4b-v3", 0.1),
        _model("openrouter", "OPENROUTER_API_KEY", "openai/gpt-4.1-mini", 2.0),
    ]
    selected = provider_bootstrap.select_provider_diverse_models(models, limit=10)
    assert [(item.provider_name, item.model_id) for item in selected] == [
        ("openrouter", "openai/gpt-4.1-mini")
    ]


def test_capability_tags_are_role_aware_without_fabricated_capabilities():
    """Known reasoning/coding/vision identifiers get bounded role tags."""
    model = _model(
        "openrouter",
        "OPENROUTER_API_KEY",
        "qwen/qwen-vl-coder",
        1.0,
    )
    tags = provider_bootstrap.capability_tags_for_discovered(model)
    assert tags[:5] == (
        "discovered",
        "chat",
        "worker",
        "writing",
        "synthesizer",
    )
    assert {"reasoning", "thinker", "verification", "verifier", "coding", "vision"} <= set(tags)


def test_bootstrap_registers_then_discovers_without_environment_runtime_reads(
    monkeypatch,
):
    """Discovery sees KV-backed credentials after the one-shot environment bootstrap."""
    environment = _complete_environment()
    observed: dict[str, str | None] = {}

    def fake_discover_all_models():
        for name in provider_bootstrap.PROVIDER_CREDENTIAL_NAMES:
            observed[name] = get_credential(name)
        return (
            [_model("openai", "OPENAI_API_KEY", "gpt-test", 1.0)],
            [],
        )

    monkeypatch.setattr(
        provider_bootstrap,
        "discover_all_models",
        fake_discover_all_models,
    )
    report = provider_bootstrap.bootstrap_provider_runtime(
        environ=environment,
        model_limit=1,
    )

    assert report.discovered_model_count == 1
    assert report.eligible_model_count == 1
    assert report.selected_agent_ids == ("openai_gpt_test",)
    assert report.enabled_agent_ids == ()
    assert report.durable_agent_pool is False
    assert all(
        observed[name] == environment[name].strip()
        for name in observed
    )


def test_bootstrap_fails_closed_when_no_model_is_discovered(monkeypatch):
    """A credential write without a usable model catalog is not reported as service-ready."""
    monkeypatch.setattr(
        provider_bootstrap,
        "discover_all_models",
        lambda: ([], []),
    )
    with pytest.raises(
        provider_bootstrap.ProviderBootstrapError,
        match="no usable models",
    ):
        provider_bootstrap.bootstrap_provider_runtime(
            environ=_complete_environment()
        )


def test_bootstrap_fails_closed_when_catalog_has_only_non_chat_models(monkeypatch):
    """A successful catalog request is not service-ready without a chat candidate."""
    monkeypatch.setattr(
        provider_bootstrap,
        "discover_all_models",
        lambda: (
            [
                _model(
                    "openai",
                    "OPENAI_API_KEY",
                    "text-embedding-3-small",
                    0.1,
                )
            ],
            [],
        ),
    )
    with pytest.raises(
        provider_bootstrap.ProviderBootstrapError,
        match="no chat-capable models",
    ):
        provider_bootstrap.bootstrap_provider_runtime(
            environ=_complete_environment()
        )


def test_durable_pool_withdraws_bootstrap_and_stale_discovered_agents(
    monkeypatch,
    tmp_path,
):
    """A refresh leaves exactly the current selected discovered models active."""
    agents_db = str(tmp_path / "agents.db")
    old_model = _model(
        "openai",
        "OPENAI_API_KEY",
        "gpt-retired-model",
        1.0,
    )
    old_agent = replace(
        agent_from_discovered(old_model),
        disabled=False,
    )
    seeded = TaskOrchestrator(
        [ModelAgent("manual_agent", "manual-model")],
        agents_db=agents_db,
    )
    seeded.sync_discovered_agents([old_agent])

    new_model = _model(
        "openrouter",
        "OPENROUTER_API_KEY",
        "qwen-current-coder",
        2.0,
    )
    monkeypatch.setattr(
        provider_bootstrap,
        "discover_all_models",
        lambda: ([new_model], []),
    )
    report = provider_bootstrap.bootstrap_provider_runtime(
        environ=_complete_environment(),
        agents_db=agents_db,
        model_limit=1,
    )

    assert report.discovered_model_count == 1
    assert report.eligible_model_count == 1
    assert report.selected_agent_ids == ("openrouter_qwen_current_coder",)
    assert report.enabled_agent_ids == ("openrouter_qwen_current_coder",)
    assert report.durable_agent_pool is True

    restarted = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model")],
        agents_db=agents_db,
    )
    assert {agent.id for agent in restarted.agents} == {
        "openrouter_qwen_current_coder"
    }
    active = restarted.agents[0]
    assert {"discovered", "chat", "worker", "synthesizer", "reasoning", "coding"} <= set(active.tags)
    assert all(
        agent.id not in {"bootstrap_agent", "openai_gpt_retired_model"}
        for agent in restarted.agents
    )


def test_cli_report_never_contains_secret_values(monkeypatch, capsys):
    """Operator evidence names credentials and agents but never prints secret material."""
    environment = _complete_environment()
    monkeypatch.setattr(os, "environ", environment)
    monkeypatch.setattr(
        provider_bootstrap,
        "discover_all_models",
        lambda: (
            [_model("openai", "OPENAI_API_KEY", "gpt-test", 1.0)],
            [],
        ),
    )
    provider_bootstrap.main(["--model-limit", "1"])
    output = capsys.readouterr().out
    report = json.loads(output)
    assert "OPENAI_API_KEY" in output
    assert report["eligible_model_count"] == 1
    assert report["selected_agent_ids"] == ["openai_gpt_test"]
    assert report["enabled_agent_ids"] == []
    assert report["durable_agent_pool"] is False
    for value in environment.values():
        assert value.strip() not in output
