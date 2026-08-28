"""Server-startup model discovery activates discovered runtime agents."""

from dataclasses import replace

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

    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert len(result["added"]) == 1
    agent = next(agent for agent in orchestrator.agents if agent.id == result["added"][0])
    assert agent.model == chat.model_id
    assert agent.disabled is False
    assert "chat" in agent.tags
    assert all(candidate.model != embedding.model_id for candidate in orchestrator.agents)
    assert all(not candidate.base_url.startswith("mock://") for candidate in orchestrator.agents)
    assert "bootstrap_agent" in result["updated"]


def test_auto_discovery_disables_paid_openrouter_without_credit(monkeypatch) -> None:
    """Catalog availability cannot promote an unaffordable paid deployment."""
    paid = DiscoveredModel(
        provider_name="openrouter",
        model_id="provider/paid-chat",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
        capabilities=("chat", "response_format"),
    )
    free = replace(paid, model_id="provider/free-chat", is_free=True)
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda: ([paid, free], []),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.openrouter_paid_inference_available",
        lambda: False,
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    _auto_discover_runtime_agents(orchestrator)

    by_model = {agent.model: agent for agent in orchestrator.candidates}
    assert by_model[paid.model_id].disabled is True
    assert by_model[free.model_id].disabled is False


def test_auto_discovery_keeps_metadata_free_general_chat_models(monkeypatch) -> None:
    """OpenAI-style model rows without capability metadata remain discoverable."""
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="gpt-5.4",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda: ([discovered], []),
    )

    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])

    result = _auto_discover_runtime_agents(orchestrator)

    assert result["added"] == ["openai_gpt_5_4"]
    assert orchestrator.agents[-1].model == discovered.model_id


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


def test_auto_discovery_preserves_sole_real_bootstrap_seed(monkeypatch) -> None:
    """A seed cannot count itself as the replacement that retires it."""
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda: ([], []),
    )
    seed = ModelAgent(
        "bootstrap_agent",
        "bootstrap-model",
        base_url="https://provider.invalid/v1",
        tags=("bootstrap_seed",),
    )
    orchestrator = TaskOrchestrator([seed])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert orchestrator.agents == [seed]


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


def test_auto_discovery_retires_mock_seed_when_real_agent_already_exists(
    monkeypatch,
) -> None:
    """Restarted discovery cannot restore mocks beside an active real agent."""
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="chat-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    real_agent = ModelAgent(
        "openai_chat_capable_model",
        discovered.model_id,
        base_url=discovered.chat_base_url,
        tags=("discovered", "chat"),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda: ([discovered], []),
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("mock_seed_agent", "mock-model", tags=("bootstrap_seed",)),
            real_agent,
        ]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert result == {"added": [], "updated": ["mock_seed_agent"]}
    assert orchestrator.agents == [real_agent]


def test_auto_discovery_retires_mock_seed_when_current_discovery_is_empty(
    monkeypatch,
) -> None:
    """A transient empty discovery cannot preserve a stale bootstrap fixture."""
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda: ([], []),
    )
    real_agent = ModelAgent(
        "existing_real_agent",
        "existing-real-model",
        base_url="https://provider.invalid/v1",
        tags=("discovered", "chat"),
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("mock_seed_agent", "mock-model", tags=("bootstrap_seed",)),
            real_agent,
        ]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert result == {"added": [], "updated": ["mock_seed_agent"]}
    assert orchestrator.agents == [real_agent]


def test_auto_discovery_preserves_operator_configured_mock(monkeypatch) -> None:
    """Only tagged bootstrap fixtures retire when real discovery succeeds."""
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
    operator_mock = ModelAgent(
        "operator_mock", "operator-model", base_url="mock://operator"
    )
    orchestrator = TaskOrchestrator([operator_mock])

    _auto_discover_runtime_agents(orchestrator)

    assert operator_mock in orchestrator.agents
