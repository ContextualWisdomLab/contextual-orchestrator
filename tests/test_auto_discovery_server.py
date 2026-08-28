"""Server-startup model discovery activates discovered runtime agents."""

import os
from unittest.mock import patch
from dataclasses import replace

from contextual_orchestrator.__main__ import _auto_discover_runtime_agents
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator


def test_auto_discovery_activates_declared_runtime_capabilities(monkeypatch) -> None:
    """Startup exposes provider-declared chat and embedding capabilities."""
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

    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert len(result["added"]) == 2
    agents = {agent.model: agent for agent in orchestrator.agents}
    assert agents[chat.model_id].disabled is False
    assert "chat" in agents[chat.model_id].tags
    assert agents[embedding.model_id].disabled is False
    assert "embedding" in agents[embedding.model_id].tags
    assert all(not candidate.base_url.startswith("mock://") for candidate in orchestrator.agents)
    assert "bootstrap_agent" in result["updated"]


def test_auto_discovery_activates_bare_chat_but_not_embedding_ids(monkeypatch) -> None:
    """A metadata-free gateway listing still activates chat deployments.

    Mirrors the user-facing report: on a bare OpenAI-compatible gateway
    (``LLM_GATEWAY_API_URL`` + ``LLM_GATEWAY_API_KEY``) whose /model/info
    merge leaves chat rows without capability evidence, chat models must be
    activated while embedding-named models stay out of the routing pool.
    """
    bare_chat = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="gpt-chat-7x",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://llm-gateway-dev.example/v1",
        auth_scheme="Bearer",
        capabilities=(),
    )
    bare_embedding = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="text-embedding-5",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://llm-gateway-dev.example/v1",
        auth_scheme="Bearer",
        capabilities=(),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args: ([bare_chat, bare_embedding], []),
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )
    result = _auto_discover_runtime_agents(orchestrator)
    assert result["added"] == ["configured_gateway_gpt_chat_7x"]
    agents = orchestrator.agents
    assert any(agent.id == "configured_gateway_gpt_chat_7x" for agent in agents)
    assert all(
        agent.model != "text-embedding-5" for agent in agents
    )


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
        lambda *args: ([paid, free], []),
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


def test_auto_discovery_leaves_pool_unchanged_without_capability_evidence(monkeypatch) -> None:
    """Startup fails closed without taking down an explicitly configured pool."""
    unclassified = DiscoveredModel(
        provider_name="openai",
        model_id="embedding-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=(),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args: ([unclassified], []),
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
def test_auto_discovery_preserves_sole_real_bootstrap_seed(monkeypatch) -> None:
    """A seed cannot count itself as the replacement that retires it."""
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *args: ([], []),
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
        lambda *args: ([discovered], []),
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
        lambda *args: ([], []),
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
        lambda *args: ([discovered], []),
    )
    operator_mock = ModelAgent(
        "operator_mock", "operator-model", base_url="mock://operator"
    )
    orchestrator = TaskOrchestrator([operator_mock])

    _auto_discover_runtime_agents(orchestrator)

    assert operator_mock in orchestrator.agents
