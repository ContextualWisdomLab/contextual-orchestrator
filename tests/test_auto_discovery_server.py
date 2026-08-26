"""Server-startup model discovery activates discovered runtime agents."""

import os
from unittest.mock import patch

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
        lambda *_args: ([chat, embedding], []),
    )

    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])

    result = _auto_discover_runtime_agents(orchestrator)

    assert len(result["added"]) == 1
    agent = next(agent for agent in orchestrator.agents if agent.id == result["added"][0])
    assert agent.model == chat.model_id
    assert agent.disabled is False
    assert "chat" in agent.tags
    assert all(candidate.model != embedding.model_id for candidate in orchestrator.agents)


def test_auto_discovery_removes_the_configured_gateway_placeholder(monkeypatch) -> None:
    """A blank discovery seed never participates in inference after expansion."""
    discovered = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="chat-capable-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args: ([discovered], []),
    )
    placeholder = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        provider_name="configured_gateway",
    )
    orchestrator = TaskOrchestrator([placeholder])

    result = _auto_discover_runtime_agents(orchestrator)

    assert result["added"] == ["configured_gateway_chat_capable_model"]
    assert [agent.model for agent in orchestrator.agents] == ["chat-capable-model"]
    assert placeholder.id not in orchestrator._group_router.snapshot()


def test_auto_discovery_removes_placeholder_for_existing_gateway_model(monkeypatch) -> None:
    """A successful gateway refresh cleans its seed even when no agent is added."""
    discovered = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="chat-capable-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args: ([discovered], []),
    )
    existing = ModelAgent(
        "configured_gateway_chat_capable_model",
        "chat-capable-model",
        provider_name="configured_gateway",
    )
    placeholder = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        provider_name="configured_gateway",
    )
    orchestrator = TaskOrchestrator([existing, placeholder])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert orchestrator.agents == [existing]


def test_auto_discovery_keeps_last_enabled_placeholder_for_disabled_gateway_model(
    monkeypatch,
) -> None:
    """Discovery preserves operator quarantine without aborting server startup."""
    discovered = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="chat-capable-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args: ([discovered], []),
    )
    existing = ModelAgent(
        "configured_gateway_chat_capable_model",
        "chat-capable-model",
        provider_name="configured_gateway",
        disabled=True,
    )
    placeholder = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        provider_name="configured_gateway",
    )
    orchestrator = TaskOrchestrator([existing, placeholder])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert orchestrator.candidates == [existing, placeholder]
    assert orchestrator.agents == [placeholder]


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
        lambda *_args: ([embedding], []),
    )

    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert [agent.id for agent in orchestrator.agents] == ["bootstrap_agent"]


def test_unrelated_discovery_keeps_configured_gateway_placeholder(monkeypatch) -> None:
    """Another healthy provider must not erase a temporarily unavailable gateway."""
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
        lambda *_args: ([discovered], []),
    )
    placeholder = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        provider_name="configured_gateway",
    )
    orchestrator = TaskOrchestrator([placeholder])

    result = _auto_discover_runtime_agents(orchestrator)

    assert result["added"] == ["openai_chat_capable_model"]
    assert placeholder in orchestrator.agents


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
        lambda *_args: ([discovered], []),
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


def test_runtime_auto_discovery_does_not_read_gateway_environment(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda sources: (captured.extend(sources) or [], []),
    )
    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])
    with patch.dict(
        os.environ,
        {
            "LLM_GATEWAY_URL": "http://unsafe.invalid/v1",
            "LLM_GATEWAY_API_KEY": "must-not-be-promoted",
        },
        clear=True,
    ):
        assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert all(source.provider_name != "configured_gateway" for source in captured)


def test_runtime_auto_discovery_skips_gateway_outside_allowlist(monkeypatch) -> None:
    """One stale persisted gateway cannot abort otherwise valid discovery."""
    captured = []
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda sources: (captured.extend(sources) or [], []),
    )
    gateway = ModelAgent(
        "configured_gateway",
        "gateway-model",
        base_url="https://gateway.example/v1",
        provider_name="configured_gateway",
    )
    orchestrator = TaskOrchestrator([gateway])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert all(source.provider_name != "configured_gateway" for source in captured)
