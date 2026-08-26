"""Server-startup model discovery activates discovered runtime agents."""

from contextual_orchestrator.__main__ import _auto_discover_runtime_agents
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator


def test_auto_discovery_activates_only_chat_capable_agents(monkeypatch) -> None:
    """Startup routing excludes discovered deployments without chat evidence."""
    chat = DiscoveredModel(
        provider_name="openai",
        model_id="chat-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    embedding = DiscoveredModel(
        provider_name="openai",
        model_id="embedding-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("embedding",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda: ([chat, embedding], []),
    )

    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])

    result = _auto_discover_runtime_agents(orchestrator)

    assert len(result["added"]) == 1
    agent = next(agent for agent in orchestrator.agents if agent.id == result["added"][0])
    assert agent.model == chat.model_id
    assert agent.disabled is False
    assert "chat" in agent.tags
    assert all(candidate.model != embedding.model_id for candidate in orchestrator.agents)
    assert all(not candidate.base_url.startswith("mock://") for candidate in orchestrator.agents)
    assert "bootstrap_agent" in result["updated"]


def test_auto_discovery_leaves_pool_unchanged_without_chat_capability_evidence(monkeypatch) -> None:
    """Startup fails closed without taking down an explicitly configured pool."""
    embedding = DiscoveredModel(
        provider_name="openai",
        model_id="embedding-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("embedding",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda: ([embedding], []),
    )

    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert [agent.id for agent in orchestrator.agents] == ["bootstrap_agent"]


def test_auto_discovery_preserves_existing_operator_settings(monkeypatch) -> None:
    """Startup discovery must not replace an operator-managed agent."""
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="chat-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda: ([discovered], []),
    )
    existing = ModelAgent(
        "openai_chat_capable_model",
        discovered.model_id,
        tags=("chat", "operator-tag"),
        disabled=True,
    )
    bootstrap = ModelAgent("bootstrap_agent", "bootstrap-model")
    orchestrator = TaskOrchestrator([bootstrap, existing])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert orchestrator.candidates == [bootstrap, existing]
