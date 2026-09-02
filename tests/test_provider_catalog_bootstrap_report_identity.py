"""Regression coverage for provider-catalog bootstrap report identities."""

from __future__ import annotations

from dataclasses import replace

import pytest

from contextual_orchestrator import TaskOrchestrator
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    ProviderModelSource,
    legacy_agent_id_for,
)
from contextual_orchestrator.provider_bootstrap import _active_agent_from_discovered
from contextual_orchestrator.provider_catalog_bootstrap import (
    bootstrap_provider_catalog_runtime,
)
from contextual_orchestrator.provider_catalog_store import InMemoryProviderCatalogStore


@pytest.fixture(autouse=True)
def isolated_credential_backend():
    """Give the catalog bootstrap regression an isolated credential registry."""
    set_backend(InMemoryCredentialBackend())
    yield
    set_backend(None)


def test_durable_catalog_report_uses_persisted_legacy_identity(tmp_path) -> None:
    """Selected and enabled catalog IDs must name the same durable agent."""
    source = ProviderModelSource(
        provider_name="openrouter",
        credential_name="OPENROUTER_API_KEY",
        list_url="https://openrouter.example/v1/models",
        chat_base_url="https://openrouter.example/v1",
    )
    model = DiscoveredModel(
        provider_name=source.provider_name,
        model_id="vendor/model-a",
        credential_name=source.credential_name,
        chat_base_url=source.chat_base_url,
        auth_scheme=source.auth_scheme,
        prompt_price_per_1k=0.0,
        completion_price_per_1k=0.0,
        is_free=True,
    )
    current_agent = _active_agent_from_discovered(model)
    legacy_id = legacy_agent_id_for(model)
    assert current_agent.id != legacy_id

    agents_db = str(tmp_path / "agents.db")
    seeded = TaskOrchestrator(
        [replace(current_agent, id=legacy_id)],
        agents_db=agents_db,
    )
    seeded.close()

    report = bootstrap_provider_catalog_runtime(
        environ={"OPENROUTER_API_KEY": "test-secret"},
        require_all_credentials=False,
        agents_db=agents_db,
        model_limit=1,
        catalog_store=InMemoryProviderCatalogStore(),
        sources=(source,),
        discovery=lambda _sources: ([model], []),
    )

    assert report.enabled_agent_ids == (legacy_id,)
    assert report.selected_agent_ids == report.enabled_agent_ids
    assert report.as_dict()["selected_agent_ids"] == [legacy_id]
