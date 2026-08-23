"""Server-startup model discovery activates discovered runtime agents."""

import pytest

from contextual_orchestrator.__main__ import _auto_discover_runtime_agents
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    ProviderDiscoveryError,
)
from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator


def test_auto_discovery_activates_discovered_agents(monkeypatch) -> None:
    """A successful startup discovery makes its agents available for routing."""
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="embedding-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("embedding",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda: ([discovered], []),
    )

    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])

    result = _auto_discover_runtime_agents(orchestrator)

    assert len(result["added"]) == 1
    agent = next(agent for agent in orchestrator.agents if agent.id == result["added"][0])
    assert agent.model == discovered.model_id
    assert agent.disabled is False
    assert orchestrator.select_capability_agent("embedding") is agent


def test_auto_discovery_rejects_empty_provider_result(monkeypatch) -> None:
    """Startup fails explicitly when every provider returns no usable model."""
    error = ProviderDiscoveryError("openai", "credentials unavailable")
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda: ([], [error]),
    )

    with pytest.raises(RuntimeError, match="automatic model discovery found no usable models"):
        _auto_discover_runtime_agents(TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")]))
