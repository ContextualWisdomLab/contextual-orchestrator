"""Server-startup model discovery activates discovered runtime agents."""

import os
from dataclasses import replace
from unittest.mock import patch

import pytest

from contextual_orchestrator.__main__ import (
    _auto_discover_runtime_agents,
    _configured_provider_hosts,
    main,
)
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator.orchestrator import (
    ModelAgent,
    ModelClient,
    TaskOrchestrator,
)


def test_configured_provider_hosts_reads_the_runtime_allowlist(monkeypatch) -> None:
    """CLI startup must give runtime discovery the deployment host allowlist."""
    monkeypatch.setenv(
        "CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS",
        "gateway.example, secondary.example ",
    )

    assert _configured_provider_hosts() == ["gateway.example", "secondary.example"]


def test_main_passes_the_runtime_allowlist_to_the_model_client(monkeypatch) -> None:
    """The server constructor receives the env-backed discovery allowlist."""
    monkeypatch.setenv(
        "CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS", "gateway.example"
    )

    def capture_client(_agents, *, client, **_kwargs):
        assert client.allowed_provider_hosts == {"gateway.example"}
        raise RuntimeError("model-client-captured")

    monkeypatch.setattr(
        "contextual_orchestrator.__main__.load_agents", lambda _path: []
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.TaskOrchestrator", capture_client
    )

    with pytest.raises(RuntimeError, match="model-client-captured"):
        main(["synthetic prompt"])


def test_explicit_provider_host_replaces_the_environment_default(monkeypatch) -> None:
    """A CLI trust-boundary override cannot inherit additional env hosts."""
    monkeypatch.setenv(
        "CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS", "environment.example"
    )

    def capture_client(_agents, *, client, **_kwargs):
        assert client.allowed_provider_hosts == {"explicit.example"}
        raise RuntimeError("model-client-captured")

    monkeypatch.setattr(
        "contextual_orchestrator.__main__.load_agents", lambda _path: []
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.TaskOrchestrator", capture_client
    )

    with pytest.raises(RuntimeError, match="model-client-captured"):
        main(
            [
                "synthetic prompt",
                "--allowed-provider-host",
                "explicit.example",
            ]
        )


def test_configured_gateway_blank_seed_expands_to_exact_catalog_models(
    monkeypatch,
) -> None:
    """An allowlisted blank seed activates only concrete catalog model IDs."""
    class CatalogProbeClient(ModelClient):
        def chat(self, agent, messages, **kwargs):  # type: ignore[override]
            del messages, kwargs
            assert agent.model in {"catalog-chat-alpha", "catalog-chat-beta"}
            return '{"ok":true}'

        def proxy_send(self, agent, endpoint, body):  # type: ignore[override]
            del endpoint
            assert agent.model in {"catalog-chat-alpha", "catalog-chat-beta"}
            assert body["response_format"]["type"] in {"json_schema", "json_object"}
            return {
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "model": agent.model,
            }

    discovered = [
        DiscoveredModel(
            provider_name="configured_gateway",
            model_id=model_id,
            credential_name="LLM_GATEWAY_API_KEY",
            chat_base_url="https://gateway.example/v1",
            auth_scheme="Bearer",
            capabilities=("chat", "response_format"),
        )
        for model_id in ("catalog-chat-alpha", "catalog-chat-beta")
    ]
    captured_sources = []
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.get_credential",
        lambda name: "registered" if name == "LLM_GATEWAY_API_KEY" else None,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda sources: (captured_sources.extend(sources) or discovered, []),
    )
    blank_seed = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        base_url="https://gateway.example",
        credential_key="LLM_GATEWAY_API_KEY",
        provider_name="configured_gateway",
        tags=("bootstrap_seed",),
    )
    orchestrator = TaskOrchestrator(
        [blank_seed],
        client=CatalogProbeClient(allowed_provider_hosts={"gateway.example"}),
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert any(source.provider_name == "configured_gateway" for source in captured_sources)
    assert result["added"] == [
        "configured_gateway_catalog_chat_alpha",
        "configured_gateway_catalog_chat_beta",
    ]
    assert {agent.model for agent in orchestrator.agents} == {
        "catalog-chat-alpha",
        "catalog-chat-beta",
    }
    assert all(agent.base_url == "https://gateway.example/v1" for agent in orchestrator.agents)
    assert all(agent.model for agent in orchestrator.agents)
    assert orchestrator.probe_structured_workflow(orchestrator.agents[0])["status"] == "ready"


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
    """A rejected gateway is fail-closed and leaves bounded audit evidence."""
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
    event = orchestrator._analytics_events[-1]
    assert event["event_name"] == "configured_gateway_discovery_unavailable"
    assert event["event_detail"] == {"reason_code": "source_not_allowlisted"}
    assert "gateway.example" not in repr(event)


def test_discovery_error_is_bounded_and_other_provider_models_activate(
    monkeypatch,
) -> None:
    """One provider failure is observable without suppressing usable discoveries."""
    from contextual_orchestrator.model_discovery import ProviderDiscoveryError

    available = DiscoveredModel(
        provider_name="openai",
        model_id="available-chat-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda _sources: (
            [available],
            [ProviderDiscoveryError("configured_gateway", "authentication_failed")],
        ),
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert result["added"] == ["openai_available_chat_model"]
    event = next(
        event
        for event in orchestrator._analytics_events
        if event["event_name"] == "provider_model_discovery_failed"
    )
    assert event["event_detail"] == {
        "provider_name": "configured_gateway",
        "reason_code": "authentication_failed",
    }


def test_runtime_auto_discovery_records_missing_gateway_credential(
    monkeypatch,
) -> None:
    """A missing gateway credential is observable without exposing its endpoint."""
    captured = []
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.get_credential", lambda _name: None
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda sources: (captured.extend(sources) or [], []),
    )
    gateway = ModelAgent(
        "configured_gateway",
        "",
        base_url="https://gateway.example/v1",
        provider_name="configured_gateway",
    )
    orchestrator = TaskOrchestrator(
        [gateway], client=ModelClient(allowed_provider_hosts={"gateway.example"})
    )

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert all(source.provider_name != "configured_gateway" for source in captured)
    event = orchestrator._analytics_events[-1]
    assert event["event_name"] == "configured_gateway_discovery_unavailable"
    assert event["event_detail"] == {"reason_code": "credential_unavailable"}
    assert "gateway.example" not in repr(event)


def test_disabled_gateway_discovery_cannot_retire_blank_seed_for_other_provider(
    monkeypatch,
) -> None:
    """Only an enabled concrete agent at the same origin may replace its seed."""
    discovered_gateway = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="catalog-chat-alpha",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda _sources: ([discovered_gateway], []),
    )
    blank_seed = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        base_url="https://gateway.example/v1",
        provider_name="configured_gateway",
        tags=("bootstrap_seed",),
    )
    disabled_discovered = replace(
        ModelAgent(
            "configured_gateway_catalog_chat_alpha",
            "catalog-chat-alpha",
            base_url="https://gateway.example/v1",
            provider_name="configured_gateway",
            tags=("discovered", "chat"),
        ),
        disabled=True,
    )
    unrelated = ModelAgent(
        "openai_available_chat", "available-chat", provider_name="openai"
    )
    orchestrator = TaskOrchestrator(
        [blank_seed, disabled_discovered, unrelated]
    )

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert blank_seed in orchestrator.agents


def test_other_provider_cannot_retire_configured_gateway_seed(monkeypatch) -> None:
    """An unrelated active catalog must not hide a failed-closed gateway seed."""
    unrelated = DiscoveredModel(
        provider_name="openrouter",
        model_id="provider/chat-model",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        is_free=True,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda _sources: ([unrelated], []),
    )
    blank_seed = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        base_url="https://gateway.example/v1",
        credential_key="LLM_GATEWAY_API_KEY",
        provider_name="configured_gateway",
        tags=("bootstrap_seed",),
    )
    orchestrator = TaskOrchestrator([blank_seed])

    result = _auto_discover_runtime_agents(orchestrator)

    assert result["added"] == ["openrouter_provider_chat_model"]
    assert blank_seed in orchestrator.agents
    assert any(agent.provider_name == "openrouter" for agent in orchestrator.agents)


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
