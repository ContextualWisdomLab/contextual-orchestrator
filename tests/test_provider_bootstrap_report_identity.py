"""Regression coverage for bootstrap report identity consistency."""

from __future__ import annotations

from dataclasses import replace

import pytest

from contextual_orchestrator import TaskOrchestrator
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend
from contextual_orchestrator.model_discovery import DiscoveredModel, legacy_agent_id_for
from contextual_orchestrator import provider_bootstrap


@pytest.fixture(autouse=True)
def isolated_credential_backend():
    """Give this report-boundary regression an isolated credential registry."""
    set_backend(InMemoryCredentialBackend())
    yield
    set_backend(None)


def test_durable_bootstrap_report_uses_persisted_legacy_identity(monkeypatch, tmp_path) -> None:
    """Selected and enabled IDs must name the same persisted durable agent."""
    model = DiscoveredModel(
        provider_name="openrouter",
        model_id="vendor/model-a",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=0.0,
        completion_price_per_1k=0.0,
        is_free=True,
    )
    current_agent = provider_bootstrap._active_agent_from_discovered(model)
    legacy_id = legacy_agent_id_for(model)
    assert current_agent.id != legacy_id

    agents_db = str(tmp_path / "agents.db")
    seeded = TaskOrchestrator(
        [replace(current_agent, id=legacy_id)],
        agents_db=agents_db,
    )
    seeded.close()

    monkeypatch.setattr(
        provider_bootstrap,
        "discover_all_models",
        lambda: ([model], []),
    )

    report = provider_bootstrap.bootstrap_provider_runtime(
        environ={"OPENROUTER_API_KEY": "test-secret"},
        require_all_credentials=False,
        agents_db=agents_db,
        model_limit=1,
    )

    assert report.enabled_agent_ids == (legacy_id,)
    assert report.selected_agent_ids == report.enabled_agent_ids
    assert report.as_dict()["selected_agent_ids"] == [legacy_id]
