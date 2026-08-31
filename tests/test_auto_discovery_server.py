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
        lambda *_args, **_kwargs: ([chat, embedding], []),
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


def test_auto_discovery_activates_a_free_vision_model_but_free_pool_excludes_it(
    monkeypatch,
) -> None:
    """A free vision-input model becomes a normal agent, not a blind-free one.

    Reproduces the second locus of ContextualWisdomLab/.github#1198's incident
    (Devin review on PR #933): ``_auto_discover_runtime_agents`` activates
    every routable discovered model directly through
    ``model_discovery.agent_from_discovered`` and never consulted
    ``model_discovery.free_discovered_models``'s exclusion at all, so NVIDIA
    NIM's ``meta/llama-3.2-90b-vision-instruct`` kept its ``cost:free`` tag and
    stayed blindly selectable by ``orchestrator/free`` through this second
    path even after that first function was fixed. Pre-fix, every assertion
    from ``_is_general_free_agent`` onward here fails: the agent is (wrongly)
    treated as blind-free-pool eligible and ``orchestrator/free`` is (wrongly)
    advertised.
    """
    vision = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="meta/llama-3.2-90b-vision-instruct",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        input_modalities=("text", "image"),
        output_modalities=("text",),
        is_free=True,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([vision], []),
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert len(result["added"]) == 1
    agent = next(
        candidate for candidate in orchestrator.agents if candidate.id == result["added"][0]
    )
    # The model is a legitimate chat-capable agent (e.g. for a caller that
    # explicitly requests it with an image) and its price evidence is honest.
    assert agent.disabled is False
    assert "cost:free" in agent.tags
    # Its own capability route can still serve it for free (price-only).
    assert orchestrator._is_free_agent(agent) is True
    # It must never be selectable by the capability-blind general chat pool.
    assert orchestrator._is_general_free_agent(agent) is False
    assert orchestrator.FREE_MODEL not in {
        row["id"] for row in orchestrator.list_openai_models()["data"]
    }


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
        lambda *_args, **_kwargs: ([bare_chat, bare_embedding], []),
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )
    result = _auto_discover_runtime_agents(orchestrator)
    assert result["added"] == ["configured_gateway_gpt_chat_7x"]
    agents = orchestrator.agents
    assert any(agent.id == "configured_gateway_gpt_chat_7x" for agent in agents)
    assert all(agent.model != "text-embedding-5" for agent in agents)


def test_auto_discovery_activates_provider_catalog_rows(monkeypatch) -> None:
    """Discovered provider rows with serving evidence enter the runtime pool."""
    provider_row = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="provider/nim-chat",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat", "response_format"),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([provider_row], []),
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert result == {
        "added": ["nvidia_nim_provider_nim_chat"],
        "updated": ["bootstrap_agent"],
    }
    agent = orchestrator.candidates[-1]
    assert agent.model == provider_row.model_id
    assert agent.disabled is False


def test_auto_discovery_never_activates_openrouter_evidence_rows(monkeypatch) -> None:
    """OpenRouter catalog rows provide evidence but never serving agents."""
    evidence = DiscoveredModel(
        provider_name="openrouter",
        model_id="provider/router-chat",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
        capabilities=("chat", "response_format"),
        evidence_only=True,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([evidence], []),
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert [agent.model for agent in orchestrator.agents] == ["bootstrap-model"]


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
        lambda *_args, **_kwargs: ([discovered], []),
    )

    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])

    result = _auto_discover_runtime_agents(orchestrator)

    assert result["added"] == ["openai_gpt_5_4"]
    assert orchestrator.agents[-1].model == discovered.model_id


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
        lambda *_args, **_kwargs: ([discovered], []),
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
        lambda *_args, **_kwargs: ([discovered], []),
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
        lambda *_args, **_kwargs: ([discovered], []),
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
        lambda *_args, **_kwargs: ([embedding], []),
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
        lambda *_args, **_kwargs: ([discovered], []),
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


def test_auto_discovery_uses_explicit_capabilities_before_model_id_heuristics(monkeypatch) -> None:
    generic_non_chat = DiscoveredModel(
        provider_name="openai",
        model_id="generic-deployment",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("embedding",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([generic_non_chat], []),
    )

    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}


def test_auto_discovery_preserves_sole_real_bootstrap_seed(monkeypatch) -> None:
    """A seed cannot count itself as the replacement that retires it."""
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *args, **_kwargs: ([], []),
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
        lambda *_args, **_kwargs: ([discovered], []),
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


def test_auto_discovery_disables_existing_discovered_paid_openrouter_without_credit(
    monkeypatch,
) -> None:
    discovered = DiscoveredModel(
        provider_name="openrouter",
        model_id="provider/paid",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        spend_admitted=False,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([discovered], []),
    )
    existing = ModelAgent(
        "openrouter_provider_paid",
        discovered.model_id,
        provider_name="openrouter",
        tags=("discovered", "chat"),
    )
    orchestrator = TaskOrchestrator([existing])

    result = _auto_discover_runtime_agents(orchestrator)

    assert result == {"added": [], "updated": [existing.id]}
    assert orchestrator.candidates[0].disabled is True


def test_runtime_auto_discovery_does_not_read_gateway_environment(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda sources, **_kwargs: (captured.extend(sources) or [], []),
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
        lambda sources, **_kwargs: (captured.extend(sources) or [], []),
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
        lambda *args, **_kwargs: ([discovered], []),
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
        lambda *args, **_kwargs: ([], []),
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
        lambda *args, **_kwargs: ([discovered], []),
    )
    operator_mock = ModelAgent(
        "operator_mock", "operator-model", base_url="mock://operator"
    )
    orchestrator = TaskOrchestrator([operator_mock])

    _auto_discover_runtime_agents(orchestrator)

    assert operator_mock in orchestrator.agents
